#!/usr/bin/env python3
"""
Deduplication Script for Blockchain Electoral Systems Corpus
Project: PaSSER-SR (Systematic Review)
Author: PaSSER-SR Team

This script merges results from all data sources and removes duplicates.
Deduplication is based on:
1. DOI match (exact)
2. Title similarity (fuzzy matching for papers without DOI)
"""

import json
import os
import re
from datetime import datetime
from typing import List, Dict, Tuple, Optional
from difflib import SequenceMatcher

# Configuration
INPUT_DIR = "results"
OUTPUT_DIR = "results"
OUTPUT_FILE = "unified_corpus.json"

# Input files
INPUT_FILES = [
    "openalex_results.json",
    "semantic_results.json",
    "core_results.json",
    "arxiv_results.json",
    "mdpi_results.json"
]

# Similarity threshold for title matching
TITLE_SIMILARITY_THRESHOLD = 0.85


def load_results(filepath: str) -> List[Dict]:
    """Load results from a JSON file."""
    if not os.path.exists(filepath):
        print(f"  ⚠️  File not found: {filepath}")
        return []
    
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        results = data.get("results", [])
        source = data.get("metadata", {}).get("source", "unknown")
        print(f"  ✓ Loaded {len(results)} results from {source}")
        return results
        
    except Exception as e:
        print(f"  ✗ Error loading {filepath}: {e}")
        return []


def normalize_doi(doi: str) -> str:
    """Normalize DOI for comparison."""
    if not doi:
        return ""
    
    # Remove URL prefix if present
    doi = doi.lower().strip()
    prefixes = [
        "https://doi.org/",
        "http://doi.org/",
        "doi.org/",
        "doi:"
    ]
    for prefix in prefixes:
        if doi.startswith(prefix):
            doi = doi[len(prefix):]
    
    return doi.strip()


def normalize_title(title: str) -> str:
    """Normalize title for comparison."""
    if not title:
        return ""
    
    # Convert to lowercase
    title = title.lower()
    
    # Remove punctuation and extra whitespace
    title = re.sub(r'[^\w\s]', ' ', title)
    title = re.sub(r'\s+', ' ', title)
    
    return title.strip()


def title_similarity(title1: str, title2: str) -> float:
    """Calculate similarity between two titles."""
    norm1 = normalize_title(title1)
    norm2 = normalize_title(title2)
    
    if not norm1 or not norm2:
        return 0.0
    
    return SequenceMatcher(None, norm1, norm2).ratio()


def find_duplicate(
    paper: Dict,
    existing_papers: List[Dict],
    doi_index: Dict[str, int],
    title_index: Dict[str, List[int]]
) -> Optional[int]:
    """
    Find if a paper is a duplicate of an existing paper.
    
    Returns:
        Index of duplicate paper if found, None otherwise
    """
    # Check DOI first (most reliable)
    doi = normalize_doi(paper.get("doi", ""))
    if doi and doi in doi_index:
        return doi_index[doi]
    
    # Check title similarity
    norm_title = normalize_title(paper.get("title", ""))
    if not norm_title:
        return None
    
    # Get first word for quick filtering
    first_word = norm_title.split()[0] if norm_title.split() else ""
    
    # Check candidates with same first word
    candidates = title_index.get(first_word, [])
    
    for idx in candidates:
        existing = existing_papers[idx]
        sim = title_similarity(paper.get("title", ""), existing.get("title", ""))
        if sim >= TITLE_SIMILARITY_THRESHOLD:
            return idx
    
    return None


def merge_paper_data(existing: Dict, new: Dict) -> Dict:
    """
    Merge data from duplicate papers, keeping the most complete information.
    """
    merged = existing.copy()
    
    # Update DOI if missing
    if not merged.get("doi") and new.get("doi"):
        merged["doi"] = new["doi"]
    
    # Update abstract if missing or new one is longer
    if not merged.get("abstract") or (new.get("abstract") and len(new.get("abstract", "")) > len(merged.get("abstract", ""))):
        merged["abstract"] = new.get("abstract", merged.get("abstract", ""))
    
    # Update authors if missing
    if not merged.get("authors") and new.get("authors"):
        merged["authors"] = new["authors"]
    
    # Update citation count (take maximum)
    merged["cited_by_count"] = max(
        merged.get("cited_by_count", 0) or 0,
        new.get("cited_by_count", 0) or 0
    )
    
    # Track all data sources
    sources = merged.get("data_sources", [merged.get("data_source", "unknown")])
    if isinstance(sources, str):
        sources = [sources]
    new_source = new.get("data_source", "unknown")
    if new_source not in sources:
        sources.append(new_source)
    merged["data_sources"] = sources
    
    # Keep fulltext URL if available
    if new.get("pdf_url") and not merged.get("pdf_url"):
        merged["pdf_url"] = new["pdf_url"]
    
    # === NEW: Merge keywords from all sources ===
    
    # Helper function to safely get list
    def get_list(d, key):
        val = d.get(key, [])
        return val if isinstance(val, list) else []
    
    # Merge OpenAlex concepts (keep highest scores)
    existing_concepts = {c.get("name"): c for c in get_list(merged, "concepts")}
    for concept in get_list(new, "concepts"):
        name = concept.get("name")
        if name:
            if name not in existing_concepts or concept.get("score", 0) > existing_concepts[name].get("score", 0):
                existing_concepts[name] = concept
    merged["concepts"] = list(existing_concepts.values())
    
    # Merge concept names (flat list)
    concept_names = set(get_list(merged, "concept_names"))
    concept_names.update(get_list(new, "concept_names"))
    merged["concept_names"] = sorted(list(concept_names))
    
    # Merge OpenAlex topics (keep first occurrence)
    if not merged.get("topics") and new.get("topics"):
        merged["topics"] = new["topics"]
    
    # Merge OpenAlex keywords
    keywords = set()
    for kw in get_list(merged, "keywords") + get_list(new, "keywords"):
        if isinstance(kw, dict):
            keywords.add(kw.get("keyword", ""))
        elif isinstance(kw, str):
            keywords.add(kw)
    merged["keywords"] = sorted([k for k in keywords if k])
    
    # Merge keyword names
    keyword_names = set(get_list(merged, "keyword_names"))
    keyword_names.update(get_list(new, "keyword_names"))
    merged["keyword_names"] = sorted(list(keyword_names))
    
    # Merge Semantic Scholar fields of study
    fields = set(get_list(merged, "fields_of_study"))
    fields.update(get_list(new, "fields_of_study"))
    merged["fields_of_study"] = sorted(list(fields))
    
    # Merge S2 fields (detailed)
    if not merged.get("s2_fields_of_study") and new.get("s2_fields_of_study"):
        merged["s2_fields_of_study"] = new["s2_fields_of_study"]
    
    # Merge CORE subjects
    subjects = set(get_list(merged, "subjects"))
    subjects.update(get_list(new, "subjects"))
    merged["subjects"] = sorted(list(subjects))
    
    # Merge arXiv categories
    categories = set(get_list(merged, "categories"))
    categories.update(get_list(new, "categories"))
    merged["categories"] = sorted(list(categories))
    
    # === Create combined all_keywords field ===
    all_keywords = set()
    all_keywords.update(get_list(merged, "concept_names"))
    all_keywords.update(get_list(merged, "keyword_names"))
    all_keywords.update(get_list(merged, "fields_of_study"))
    all_keywords.update(get_list(merged, "subjects"))
    all_keywords.update(get_list(merged, "categories"))
    all_keywords.update(get_list(merged, "keywords") if isinstance(merged.get("keywords", [None])[0] if merged.get("keywords") else None, str) else [])
    
    # Remove empty strings
    all_keywords.discard("")
    merged["all_keywords"] = sorted(list(all_keywords))
    
    return merged


def deduplicate_corpus(all_papers: List[Dict]) -> List[Dict]:
    """
    Deduplicate papers and merge information from duplicates.
    """
    unique_papers = []
    doi_index = {}  # DOI -> index in unique_papers
    title_index = {}  # first word of title -> list of indices
    
    duplicates_found = 0
    
    for paper in all_papers:
        # Find potential duplicate
        dup_idx = find_duplicate(paper, unique_papers, doi_index, title_index)
        
        if dup_idx is not None:
            # Merge with existing paper
            unique_papers[dup_idx] = merge_paper_data(unique_papers[dup_idx], paper)
            duplicates_found += 1
        else:
            # Add as new paper
            idx = len(unique_papers)
            
            # Ensure data_sources is a list
            paper["data_sources"] = [paper.get("data_source", "unknown")]
            
            unique_papers.append(paper)
            
            # Update indices
            doi = normalize_doi(paper.get("doi", ""))
            if doi:
                doi_index[doi] = idx
            
            norm_title = normalize_title(paper.get("title", ""))
            if norm_title:
                first_word = norm_title.split()[0] if norm_title.split() else ""
                if first_word not in title_index:
                    title_index[first_word] = []
                title_index[first_word].append(idx)
    
    print(f"\nDeduplication results:")
    print(f"  Total input papers: {len(all_papers)}")
    print(f"  Duplicates merged: {duplicates_found}")
    print(f"  Unique papers: {len(unique_papers)}")
    
    return unique_papers


def add_corpus_id(papers: List[Dict]) -> List[Dict]:
    """Add unique corpus ID to each paper."""
    for i, paper in enumerate(papers, 1):
        paper["corpus_id"] = f"BES-{i:04d}"  # Blockchain Electoral Systems
    return papers


def calculate_statistics(papers: List[Dict]) -> Dict:
    """Calculate corpus statistics."""
    stats = {
        "total_papers": len(papers),
        "papers_by_year": {},
        "papers_by_source": {},
        "papers_with_doi": 0,
        "papers_with_abstract": 0,
        "papers_with_fulltext": 0,
        "multi_source_papers": 0,
        # === NEW ===
        "papers_with_keywords": 0,
        "total_unique_keywords": set(),
        "top_keywords": {}
    }
    
    for paper in papers:
        # By year
        year = paper.get("year")
        if year:
            stats["papers_by_year"][year] = stats["papers_by_year"].get(year, 0) + 1
        
        # By source
        sources = paper.get("data_sources", [])
        for source in sources:
            stats["papers_by_source"][source] = stats["papers_by_source"].get(source, 0) + 1
        
        # Multi-source
        if len(sources) > 1:
            stats["multi_source_papers"] += 1
        
        # With DOI
        if paper.get("doi"):
            stats["papers_with_doi"] += 1
        
        # With abstract
        if paper.get("abstract"):
            stats["papers_with_abstract"] += 1
        
        # With fulltext
        if paper.get("pdf_url") or paper.get("fulltext_available"):
            stats["papers_with_fulltext"] += 1
    
            # === NEW: Keywords statistics ===
        keywords = paper.get("all_keywords", [])
        if keywords:
            stats["papers_with_keywords"] += 1
            stats["total_unique_keywords"].update(keywords)
            for kw in keywords:
                stats["top_keywords"][kw] = stats["top_keywords"].get(kw, 0) + 1
    
    # Convert set to count for JSON serialization
    stats["total_unique_keywords"] = len(stats["total_unique_keywords"])
    
    # Keep only top 50 keywords
    stats["top_keywords"] = dict(sorted(stats["top_keywords"].items(), key=lambda x: -x[1])[:50])
    
    return stats


def save_corpus(papers: List[Dict], stats: Dict, output_path: str):
    """Save unified corpus to JSON file."""
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    
    corpus = {
        "metadata": {
            "name": "Blockchain Electoral Systems Corpus",
            "description": "Unified corpus for systematic review of blockchain applications in electoral processes",
            "created_at": datetime.now().isoformat(),
            "years_covered": "2015-2025",
            "sources": ["OpenAlex", "Semantic Scholar", "CORE", "arXiv"],
            "statistics": stats
        },
        "papers": papers
    }
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(corpus, f, indent=2, ensure_ascii=False)
    
    print(f"\nSaved unified corpus to {output_path}")


def main():
    """Main execution function."""
    print("=" * 60)
    print("Corpus Deduplication and Unification")
    print("=" * 60)
    
    # Load all results
    print("\nLoading results from all sources...")
    all_papers = []
    
    for filename in INPUT_FILES:
        filepath = os.path.join(INPUT_DIR, filename)
        results = load_results(filepath)
        all_papers.extend(results)
    
    print(f"\nTotal papers loaded: {len(all_papers)}")
    
    if not all_papers:
        print("No papers to process. Please run the search scripts first.")
        return
    
    # Deduplicate
    print("\nDeduplicating...")
    unique_papers = deduplicate_corpus(all_papers)
    
    # Add corpus IDs
    print("\nAssigning corpus IDs...")
    unique_papers = add_corpus_id(unique_papers)
    
    # Sort by year (descending) then by citation count
    unique_papers.sort(key=lambda x: (-(x.get("year") or 0), -(x.get("cited_by_count") or 0)))
    
    # Calculate statistics
    stats = calculate_statistics(unique_papers)
    
    # Save corpus
    output_path = os.path.join(OUTPUT_DIR, OUTPUT_FILE)
    save_corpus(unique_papers, stats, output_path)
    
    # Print summary
    print("\n" + "=" * 60)
    print("CORPUS STATISTICS")
    print("=" * 60)
    print(f"Total unique papers: {stats['total_papers']}")
    print(f"Papers with DOI: {stats['papers_with_doi']}")
    print(f"Papers with abstract: {stats['papers_with_abstract']}")
    print(f"Papers with fulltext URL: {stats['papers_with_fulltext']}")
    print(f"Papers found in multiple sources: {stats['multi_source_papers']}")

    print(f"Papers with keywords: {stats['papers_with_keywords']}")
    print(f"Total unique keywords: {stats['total_unique_keywords']}")
    
    print("\nTop 10 keywords:")
    for kw, count in list(stats['top_keywords'].items())[:10]:
        print(f"  {kw}: {count}")
            
    print("\nPapers by source:")
    for source, count in sorted(stats['papers_by_source'].items()):
        print(f"  {source}: {count}")
    
    print("\nPapers by year (last 5 years):")
    for year in sorted(stats['papers_by_year'].keys(), reverse=True)[:5]:
        print(f"  {year}: {stats['papers_by_year'][year]}")
    
    print(f"\nOutput file: {output_path}")
    print("\n✓ Corpus ready for LLM screening!")


if __name__ == "__main__":
    main()
