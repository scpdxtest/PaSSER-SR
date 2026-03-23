#!/usr/bin/env python3
"""
arXiv Search Script for Blockchain Electoral Systems Corpus
Project: PaSSER-SR (Systematic Review)
Author: PaSSER-SR Team

arXiv API is free and does not require authentication.
Rate limit: 1 request every 3 seconds
"""

import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import json
import time
import os
from datetime import datetime
from typing import List, Dict

# Configuration
OUTPUT_DIR = "results"
OUTPUT_FILE = "arxiv_results.json"
API_BASE = "http://export.arxiv.org/api/query"

# Search queries for arXiv
# arXiv uses specific query syntax: https://info.arxiv.org/help/api/user-manual.html
SEARCH_QUERIES = [
    'all:"blockchain" AND all:"voting"',
    'all:"blockchain" AND all:"election"',
    'all:"blockchain" AND all:"e-voting"',
    'all:"distributed ledger" AND all:"voting"',
    'all:"smart contract" AND all:"voting"',
    'all:"smart contract" AND all:"election"',
    'all:"decentralized" AND all:"voting" AND all:"election"',
]

EXCLUDE_TERMS = ["DAO voting", "governance voting", "token voting"]

# arXiv namespaces
ATOM_NS = "{http://www.w3.org/2005/Atom}"
ARXIV_NS = "{http://arxiv.org/schemas/atom}"


def fetch_arxiv_results(
    query: str,
    start: int = 0,
    max_results: int = 100
) -> List[Dict]:
    """
    Fetch results from arXiv API.
    
    Args:
        query: arXiv search query
        start: Start index for pagination
        max_results: Maximum results to return
    
    Returns:
        List of parsed entries
    """
    params = {
        "search_query": query,
        "start": start,
        "max_results": max_results,
        "sortBy": "relevance",
        "sortOrder": "descending"
    }
    
    url = f"{API_BASE}?{urllib.parse.urlencode(params)}"
    
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            xml_data = response.read().decode("utf-8")
        
        # Parse XML
        root = ET.fromstring(xml_data)
        entries = []
        
        for entry in root.findall(f"{ATOM_NS}entry"):
            parsed = parse_entry(entry)
            if parsed:
                entries.append(parsed)
        
        return entries
        
    except Exception as e:
        print(f"Error fetching arXiv: {e}")
        return []


def parse_entry(entry: ET.Element) -> Dict:
    """Parse a single arXiv entry XML element."""
    
    def get_text(tag: str) -> str:
        elem = entry.find(f"{ATOM_NS}{tag}")
        return elem.text.strip() if elem is not None and elem.text else ""
    
    # Get arXiv ID
    arxiv_id = get_text("id")
    if arxiv_id:
        # Extract just the ID part (e.g., "2301.12345" from full URL)
        arxiv_id = arxiv_id.split("/abs/")[-1]
    
    # Get title (remove newlines)
    title = get_text("title").replace("\n", " ").strip()
    
    # Get abstract (called "summary" in arXiv API)
    abstract = get_text("summary").replace("\n", " ").strip()
    
    # Get authors
    authors = []
    for author in entry.findall(f"{ATOM_NS}author"):
        name = author.find(f"{ATOM_NS}name")
        if name is not None and name.text:
            authors.append(name.text.strip())
    
    # Get publication date
    published = get_text("published")
    year = None
    if published:
        try:
            year = int(published[:4])
        except:
            pass
    
    # Get DOI if available
    doi = ""
    for link in entry.findall(f"{ATOM_NS}link"):
        if link.get("title") == "doi":
            href = link.get("href", "")
            if "doi.org" in href:
                doi = href.split("doi.org/")[-1]
    
    # Also check arxiv:doi element
    doi_elem = entry.find(f"{ARXIV_NS}doi")
    if doi_elem is not None and doi_elem.text:
        doi = doi_elem.text.strip()
    
    # Get categories
    categories = []
    for category in entry.findall(f"{ATOM_NS}category"):
        term = category.get("term")
        if term:
            categories.append(term)
    
    # Primary category
    primary_category = entry.find(f"{ARXIV_NS}primary_category")
    primary_cat = primary_category.get("term") if primary_category is not None else ""
    
    # Get PDF link
    pdf_url = ""
    for link in entry.findall(f"{ATOM_NS}link"):
        if link.get("type") == "application/pdf":
            pdf_url = link.get("href", "")
            break
    
    return {
        "arxiv_id": arxiv_id,
        "title": title,
        "abstract": abstract,
        "authors": authors,
        "year": year,
        "published": published,
        "doi": doi,
        "categories": categories,
        "primary_category": primary_cat,
        "pdf_url": pdf_url,
        "url": f"https://arxiv.org/abs/{arxiv_id}"
    }


def fetch_all_results(queries: List[str], max_per_query: int = 200) -> List[Dict]:
    """
    Fetch results for all queries with deduplication.
    """
    all_results = []
    seen_ids = set()
    
    print(f"Running {len(queries)} search queries...")
    print("-" * 50)
    
    for i, query in enumerate(queries, 1):
        print(f"\n[{i}/{len(queries)}] Query: {query}")
        
        start = 0
        query_results = 0
        
        while start < max_per_query:
            entries = fetch_arxiv_results(
                query=query,
                start=start,
                max_results=100
            )
            
            if not entries:
                break
            
            # Deduplicate by arXiv ID
            new_entries = []
            for entry in entries:
                arxiv_id = entry.get("arxiv_id")
                if arxiv_id and arxiv_id not in seen_ids:
                    seen_ids.add(arxiv_id)
                    new_entries.append(entry)
            
            all_results.extend(new_entries)
            query_results += len(new_entries)
            
            print(f"  Start {start}: {len(new_entries)} new papers (total unique: {len(all_results)})")
            
            if len(entries) < 100:
                break
            
            start += 100
            
            # Rate limiting - arXiv asks for 3 seconds between requests
            time.sleep(3.0)
        
        print(f"  Query total: {query_results} papers")
        time.sleep(3.0)
    
    return all_results


def normalize_result(entry: Dict) -> Dict:
    """
    Normalize arXiv entry to unified corpus format.
    """
    return {
        "id": entry.get("arxiv_id", ""),
        "doi": entry.get("doi", ""),
        "title": entry.get("title", ""),
        "abstract": entry.get("abstract", ""),
        "authors": entry.get("authors", []),
        "year": entry.get("year"),
        "type": "preprint",
        "source_name": "arXiv",
        "cited_by_count": 0,  # arXiv doesn't provide citation counts
        "url": entry.get("url", ""),
        "pdf_url": entry.get("pdf_url", ""),
        "categories": entry.get("categories", []),
        "data_source": "arxiv",
        "fetched_at": datetime.now().isoformat()
    }


def should_exclude(result: Dict) -> bool:
    """Check if result should be excluded."""
    title = (result.get("title") or "").lower()
    abstract = (result.get("abstract") or "").lower()
    combined = title + " " + abstract
    
    election_terms = ["election", "electoral", "ballot", "referendum", "voter"]
    has_election_context = any(et in combined for et in election_terms)
    
    if "dao" in combined and "voting" in combined and not has_election_context:
        return True
    if "governance voting" in combined and not has_election_context:
        return True
    
    return False


def filter_by_year(results: List[Dict], start_year: int = 2015, end_year: int = 2025) -> List[Dict]:
    """Filter results by publication year."""
    return [r for r in results if r.get("year") and start_year <= r["year"] <= end_year]


def save_results(results: List[Dict], output_path: str):
    """Save results to JSON file."""
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({
            "metadata": {
                "source": "arXiv",
                "query_date": datetime.now().isoformat(),
                "total_results": len(results),
                "years": "2015-2025",
                "note": "Preprints - may have later published versions"
            },
            "results": results
        }, f, indent=2, ensure_ascii=False)
    
    print(f"Saved {len(results)} results to {output_path}")


def main():
    """Main execution function."""
    print("=" * 60)
    print("arXiv Search for Blockchain Electoral Systems")
    print("=" * 60)
    
    # Fetch results
    raw_results = fetch_all_results(SEARCH_QUERIES, max_per_query=200)
    
    # Normalize results
    print("\nNormalizing results...")
    normalized = [normalize_result(entry) for entry in raw_results]
    
    # Filter by year
    print("Filtering by year (2015-2025)...")
    year_filtered = filter_by_year(normalized)
    print(f"After year filter: {len(year_filtered)}")
    
    # Filter out excluded terms
    print("Filtering excluded terms...")
    filtered = [r for r in year_filtered if not should_exclude(r)]
    print(f"After exclusion filter: {len(filtered)}")
    
    # Filter out results without abstract
    with_abstract = [r for r in filtered if r.get("abstract")]
    print(f"With abstract: {len(with_abstract)}")
    
    # Save results
    output_path = os.path.join(OUTPUT_DIR, OUTPUT_FILE)
    save_results(with_abstract, output_path)
    
    # Print summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total unique papers: {len(raw_results)}")
    print(f"After all filters: {len(with_abstract)}")
    print(f"Output file: {output_path}")
    
    # Show category distribution
    if with_abstract:
        categories = {}
        for r in with_abstract:
            for cat in r.get("categories", []):
                categories[cat] = categories.get(cat, 0) + 1
        
        print("\nTop categories:")
        for cat, count in sorted(categories.items(), key=lambda x: -x[1])[:10]:
            print(f"  {cat}: {count}")


if __name__ == "__main__":
    main()
