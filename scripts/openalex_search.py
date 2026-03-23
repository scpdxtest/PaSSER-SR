#!/usr/bin/env python3
"""
OpenAlex Search Script for Blockchain Electoral Systems Corpus
Project: PaSSER-SR (Systematic Review)
Author: PaSSER-SR Team

Based on Search Specification (20 January 2026):
- Group A: blockchain, distributed ledger, DLT, smart contract, decentralized/decentralised
- Group B: voting, election, e-voting, electoral, ballot, referendum, voter registration, vote counting
- Excluded: DAO voting, governance voting, poll/polling
- Years: 2015-2025
- Language: English only
- Document types: Journal articles, Conference papers
"""

import requests
import json
import time
import os
from datetime import datetime
from typing import List, Dict, Optional

# Configuration
OUTPUT_DIR = "results"
OUTPUT_FILE = "openalex_results.json"
API_BASE = "https://api.openalex.org/works"
EMAIL = "your-email@example.com"  # Replace with your email for polite pool

# Search terms from specification
GROUP_A = [
    "blockchain",
    "distributed ledger",
    "DLT",
    "smart contract",
    "decentralized",
    "decentralised"
]

GROUP_B = [
    "voting",
    "election",
    "e-voting",
    "electoral",
    "ballot",
    "referendum",
    "voter registration",
    "vote counting"
]

# Terms to exclude (will filter in post-processing)
EXCLUDE_TERMS = [
    "DAO voting",
    "governance voting",
    "governance token",
    "token voting",
    "poll",
    "polling",
    "opinion poll"
]


def build_search_query() -> str:
    """Build OpenAlex search query from term groups."""
    # OpenAlex uses simple text search
    # We'll search for combinations and filter results
    group_a_str = " OR ".join([f'"{term}"' for term in GROUP_A])
    group_b_str = " OR ".join([f'"{term}"' for term in GROUP_B])
    return f"({group_a_str}) AND ({group_b_str})"


def fetch_openalex_results(
    query: str,
    start_year: int = 2015,
    end_year: int = 2025,
    per_page: int = 200,
    max_results: int = 2000
) -> List[Dict]:
    """
    Fetch results from OpenAlex API with pagination.
    
    Args:
        query: Search query string
        start_year: Start year for publication filter
        end_year: End year for publication filter
        per_page: Results per page (max 200)
        max_results: Maximum total results to fetch
    
    Returns:
        List of work dictionaries
    """
    all_results = []
    cursor = "*"
    page_count = 0
    
    print(f"Starting OpenAlex search...")
    print(f"Query: {query[:100]}...")
    print(f"Years: {start_year}-{end_year}")
    print(f"Max results: {max_results}")
    print("-" * 50)
    
    while len(all_results) < max_results:
        params = {
            "search": query,
            "filter": f"publication_year:{start_year}-{end_year},language:en,type:article|proceedings-article",
            "per_page": per_page,
            "cursor": cursor,
            "mailto": EMAIL,
            "select": "id,doi,title,abstract_inverted_index,authorships,publication_year,primary_location,type,cited_by_count"
        }
        
        try:
            response = requests.get(API_BASE, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            results = data.get("results", [])
            if not results:
                print("No more results.")
                break
            
            all_results.extend(results)
            page_count += 1
            
            print(f"Page {page_count}: Fetched {len(results)} results (Total: {len(all_results)})")
            
            # Get next cursor
            meta = data.get("meta", {})
            cursor = meta.get("next_cursor")
            if not cursor:
                print("No more pages.")
                break
            
            # Rate limiting - be polite
            time.sleep(0.1)
            
        except requests.exceptions.RequestException as e:
            print(f"Error fetching page {page_count + 1}: {e}")
            break
    
    print(f"\nTotal fetched: {len(all_results)} results")
    return all_results


def reconstruct_abstract(inverted_index: Optional[Dict]) -> str:
    """
    Reconstruct abstract text from OpenAlex inverted index format.
    
    Args:
        inverted_index: Dictionary mapping words to position lists
    
    Returns:
        Reconstructed abstract string
    """
    if not inverted_index:
        return ""
    
    # Create position -> word mapping
    positions = {}
    for word, indices in inverted_index.items():
        for idx in indices:
            positions[idx] = word
    
    # Sort by position and join
    if not positions:
        return ""
    
    max_pos = max(positions.keys())
    words = [positions.get(i, "") for i in range(max_pos + 1)]
    return " ".join(words)


def extract_authors(authorships: List[Dict]) -> List[str]:
    """Extract author names from OpenAlex authorships."""
    authors = []
    for authorship in authorships:
        author = authorship.get("author", {})
        name = author.get("display_name", "")
        if name:
            authors.append(name)
    return authors


def normalize_result(work: Dict) -> Dict:
    """
    Normalize OpenAlex work to unified corpus format.
    """
    # Extract DOI (remove URL prefix if present)
    doi = work.get("doi", "")
    if doi and doi.startswith("https://doi.org/"):
        doi = doi.replace("https://doi.org/", "")
    
    # Get primary location info
    primary_location = work.get("primary_location", {}) or {}
    source = primary_location.get("source", {}) or {}
    
    # === NEW: Extract concepts (keywords) ===
    # Concepts are OpenAlex's way of tagging papers with topics
    # Each concept has: id, display_name, level (0=broad, 5=specific), score (relevance)
    concepts_raw = work.get("concepts", []) or []
    concepts = [
        {
            "name": c.get("display_name", ""),
            "level": c.get("level", 0),
            "score": round(c.get("score", 0), 4)
        }
        for c in concepts_raw
        if c.get("display_name")  # Skip empty names
    ]
    # Sort by score (most relevant first) and take top 15
    concepts = sorted(concepts, key=lambda x: x["score"], reverse=True)[:15]
    concept_names = [c["name"] for c in concepts]
    
    # === NEW: Extract topics (newer, more accurate than concepts) ===
    # Topics are hierarchical: domain > field > subfield > topic
    topics_raw = work.get("topics", []) or []
    topics = []
    for t in topics_raw[:5]:  # Top 5 topics
        topic_entry = {
            "name": t.get("display_name", ""),
            "score": round(t.get("score", 0), 4)
        }
        # Add hierarchy if available
        if t.get("subfield"):
            topic_entry["subfield"] = t["subfield"].get("display_name", "")
        if t.get("field"):
            topic_entry["field"] = t["field"].get("display_name", "")
        if t.get("domain"):
            topic_entry["domain"] = t["domain"].get("display_name", "")
        topics.append(topic_entry)
    
    # === NEW: Extract keywords (author-provided, if available) ===
    keywords_raw = work.get("keywords", []) or []
    keywords = [
        {
            "keyword": k.get("keyword", "") or k.get("display_name", ""),
            "score": round(k.get("score", 0), 4)
        }
        for k in keywords_raw
        if k.get("keyword") or k.get("display_name")
    ][:10]
    keyword_names = [k["keyword"] for k in keywords]
    
    return {
        "id": work.get("id", ""),
        "doi": doi,
        "title": work.get("title", ""),
        "abstract": reconstruct_abstract(work.get("abstract_inverted_index")),
        "authors": extract_authors(work.get("authorships", [])),
        "year": work.get("publication_year"),
        "type": work.get("type", ""),
        "source_name": source.get("display_name", ""),
        "cited_by_count": work.get("cited_by_count", 0),
        "url": work.get("id", ""),
        "data_source": "openalex",
        "fetched_at": datetime.now().isoformat(),
        # === NEW FIELDS ===
        "concepts": concepts,
        "concept_names": concept_names,
        "topics": topics,
        "keywords": keywords,
        "keyword_names": keyword_names,
        # Combined flat list for easy searching
        "all_keywords": list(set(concept_names + keyword_names))
    }


def should_exclude(result: Dict) -> bool:
    """
    Check if result should be excluded based on exclusion terms.
    
    Args:
        result: Normalized result dictionary
    
    Returns:
        True if should be excluded, False otherwise
    """
    title = (result.get("title") or "").lower()
    abstract = (result.get("abstract") or "").lower()
    combined = title + " " + abstract
    
    for term in EXCLUDE_TERMS:
        if term.lower() in combined:
            # Check if it's actually about elections/voting (not just DAO/governance)
            election_terms = ["election", "electoral", "ballot", "referendum", "voter"]
            has_election_context = any(et in combined for et in election_terms)
            
            # If it mentions DAO/governance voting but also elections, keep it
            if "dao" in combined.lower() and not has_election_context:
                return True
            if "governance voting" in combined.lower() and not has_election_context:
                return True
            if term.lower() in ["poll", "polling"] and "opinion" in combined:
                return True
    
    return False


def save_results(results: List[Dict], output_path: str):
    """Save results to JSON file."""
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({
            "metadata": {
                "source": "OpenAlex",
                "query_date": datetime.now().isoformat(),
                "total_results": len(results),
                "years": "2015-2025",
                "language": "English",
                "document_types": ["article", "proceedings-article"]
            },
            "results": results
        }, f, indent=2, ensure_ascii=False)
    
    print(f"Saved {len(results)} results to {output_path}")


def main():
    """Main execution function."""
    print("=" * 60)
    print("OpenAlex Search for Blockchain Electoral Systems")
    print("=" * 60)
    
    # Build query
    query = build_search_query()
    print(f"\nSearch query:\n{query}\n")
    
    # Fetch results
    raw_results = fetch_openalex_results(
        query=query,
        start_year=2015,
        end_year=2025,
        max_results=2000
    )
    
    # Normalize results
    print("\nNormalizing results...")
    normalized = [normalize_result(work) for work in raw_results]
    
    # Filter out excluded terms
    print("Filtering excluded terms...")
    before_filter = len(normalized)
    filtered = [r for r in normalized if not should_exclude(r)]
    after_filter = len(filtered)
    print(f"Filtered out {before_filter - after_filter} results")
    
    # Filter out results without abstract (can't screen without abstract)
    with_abstract = [r for r in filtered if r.get("abstract")]
    print(f"Results with abstract: {len(with_abstract)} (removed {len(filtered) - len(with_abstract)} without abstract)")
    
    # Save results
    output_path = os.path.join(OUTPUT_DIR, OUTPUT_FILE)
    save_results(with_abstract, output_path)
    
    # Print summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total fetched from API: {len(raw_results)}")
    print(f"After normalization: {len(normalized)}")
    print(f"After exclusion filter: {len(filtered)}")
    print(f"With abstract (final): {len(with_abstract)}")
    print(f"Output file: {output_path}")
    
    # Show sample
    if with_abstract:
        print("\nSample result:")
        sample = with_abstract[0]
        print(f"  Title: {sample['title'][:80]}...")
        print(f"  DOI: {sample['doi']}")
        print(f"  Year: {sample['year']}")
        print(f"  Authors: {', '.join(sample['authors'][:3])}...")


if __name__ == "__main__":
    main()
