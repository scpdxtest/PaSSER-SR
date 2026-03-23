#!/usr/bin/env python3
"""
CORE Search Script for Blockchain Electoral Systems Corpus
Project: PaSSER-SR (Systematic Review)
Author: PaSSER-SR Team

CORE API requires registration for API key: https://core.ac.uk/services/api
Free tier: 10,000 requests/month
"""

import requests
import json
import time
import os
from datetime import datetime
from typing import List, Dict, Optional

# Configuration
OUTPUT_DIR = "results"
OUTPUT_FILE = "core_results.json"
API_BASE = "https://api.core.ac.uk/v3/search/works"
API_KEY = "jKmXkoVOAzsplYiHxyBd3PnGh51tQ6D4"  # Register at https://core.ac.uk/services/api

# Search terms
SEARCH_QUERIES = [
    "blockchain voting",
    "blockchain election",
    "blockchain e-voting",
    "blockchain electoral",
    "distributed ledger voting",
    "smart contract voting election"
]

EXCLUDE_TERMS = ["DAO voting", "governance voting", "token voting"]


def fetch_core_results(
    query: str,
    limit: int = 100,
    offset: int = 0
) -> Dict:
    """
    Fetch results from CORE API.
    
    Args:
        query: Search query string
        limit: Results per request (max 100)
        offset: Pagination offset
    
    Returns:
        API response dictionary
    """
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    
    # CORE uses POST for search
    payload = {
        "q": query,
        "limit": limit,
        "offset": offset,
        "entity_type": "works",
        "stats": False
    }
    
    try:
        response = requests.post(API_BASE, headers=headers, json=payload, timeout=30)
        
        if response.status_code == 401:
            print("ERROR: Invalid API key. Please register at https://core.ac.uk/services/api")
            return {"results": [], "totalHits": 0}
        
        if response.status_code == 429:
            print("Rate limited. Waiting 60 seconds...")
            time.sleep(60)
            return fetch_core_results(query, limit, offset)
        
        response.raise_for_status()
        return response.json()
        
    except requests.exceptions.RequestException as e:
        print(f"Error: {e}")
        return {"results": [], "totalHits": 0}


def fetch_all_results(queries: List[str], max_per_query: int = 500) -> List[Dict]:
    """
    Fetch results for all queries with deduplication.
    """
    all_results = []
    seen_ids = set()
    
    print(f"Running {len(queries)} search queries...")
    print("-" * 50)
    
    for i, query in enumerate(queries, 1):
        print(f"\n[{i}/{len(queries)}] Query: {query}")
        
        offset = 0
        query_results = 0
        
        while offset < max_per_query:
            data = fetch_core_results(
                query=query,
                limit=100,
                offset=offset
            )
            
            results = data.get("results", [])
            if not results:
                break
            
            # Deduplicate by CORE ID
            new_results = []
            for item in results:
                item_id = item.get("id")
                if item_id and item_id not in seen_ids:
                    seen_ids.add(item_id)
                    new_results.append(item)
            
            all_results.extend(new_results)
            query_results += len(new_results)
            
            print(f"  Offset {offset}: {len(new_results)} new papers (total unique: {len(all_results)})")
            
            total_hits = data.get("totalHits", 0)
            if offset + 100 >= total_hits:
                break
            
            offset += 100
            time.sleep(1.0)
        
        print(f"  Query total: {query_results} papers")
        time.sleep(2.0)
    
    return all_results


def normalize_result(item: Dict) -> Dict:
    """
    Normalize CORE result to unified corpus format.
    """
    # Extract DOI (remove URL prefix if present)
    doi = item.get("doi", "")
    if doi and doi.startswith("https://doi.org/"):
        doi = doi.replace("https://doi.org/", "")
    
    # Extract authors
    authors_raw = item.get("authors", []) or []
    authors = []
    for author in authors_raw:
        if isinstance(author, dict):
            name = author.get("name", "")
            if name:
                authors.append(name)
        elif isinstance(author, str):
            authors.append(author)
    
    # Extract year from publishedDate or yearPublished
    year = None
    pub_date = item.get("publishedDate", "") or item.get("yearPublished", "")
    if pub_date:
        if isinstance(pub_date, int):
            year = pub_date
        elif isinstance(pub_date, str):
            # Try to extract year from date string (e.g., "2021-05-15" or "2021")
            import re
            year_match = re.search(r'\b(19|20)\d{2}\b', pub_date)
            if year_match:
                year = int(year_match.group(0))
    
    # === Extract subjects/topics ===
    # CORE provides fieldOfStudy as a string or list
    field_of_study = item.get("fieldOfStudy", "")
    if isinstance(field_of_study, str):
        fields = [field_of_study] if field_of_study else []
    elif isinstance(field_of_study, list):
        fields = [f for f in field_of_study if f]
    else:
        fields = []
    
    # CORE also has subjects (more specific)
    subjects_raw = item.get("subjects", []) or []
    subjects = [s for s in subjects_raw if isinstance(s, str) and s]
    
    # Document type can also be informative
    doc_type = item.get("documentType", "")
    
    # Combined keywords
    all_keywords = list(set(fields + subjects))
    
    return {
        "id": str(item.get("id", "")),
        "doi": doi,
        "title": item.get("title", ""),
        "abstract": item.get("abstract", ""),
        "authors": authors,
        "year": year,
        "type": doc_type or "unknown",
        "source_name": item.get("publisher", "") or (item.get("journals", [{}])[0].get("title", "") if item.get("journals") else ""),
        "cited_by_count": item.get("citationCount", 0),
        "url": item.get("downloadUrl", "") or (item.get("sourceFulltextUrls", [""])[0] if item.get("sourceFulltextUrls") else ""),
        "fulltext_available": bool(item.get("fullText") or item.get("downloadUrl")),
        "data_source": "core",
        "fetched_at": datetime.now().isoformat(),
        # === NEW FIELDS ===
        "fields_of_study": fields,
        "subjects": subjects,
        "all_keywords": all_keywords
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
    filtered = []
    for r in results:
        year = r.get("year")
        if year and start_year <= year <= end_year:
            filtered.append(r)
        elif not year:
            # Keep results without year (can filter manually later)
            filtered.append(r)
    return filtered


def save_results(results: List[Dict], output_path: str):
    """Save results to JSON file."""
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({
            "metadata": {
                "source": "CORE",
                "query_date": datetime.now().isoformat(),
                "total_results": len(results),
                "years": "2015-2025",
                "note": "Open access papers with full-text availability"
            },
            "results": results
        }, f, indent=2, ensure_ascii=False)
    
    print(f"Saved {len(results)} results to {output_path}")


def main():
    """Main execution function."""
    print("=" * 60)
    print("CORE Search for Blockchain Electoral Systems")
    print("=" * 60)
    
    if API_KEY == "YOUR_CORE_API_KEY":
        print("\n⚠️  WARNING: Please set your CORE API key!")
        print("Register at: https://core.ac.uk/services/api")
        print("Then update API_KEY in this script.\n")
        return
    
    # Fetch results
    raw_results = fetch_all_results(SEARCH_QUERIES, max_per_query=500)
    
    # Normalize results
    print("\nNormalizing results...")
    normalized = [normalize_result(item) for item in raw_results]
    
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
    
    # Count fulltext availability
    fulltext_count = sum(1 for r in with_abstract if r.get("fulltext_available"))
    print(f"With full-text available: {fulltext_count}")
    print(f"Output file: {output_path}")


if __name__ == "__main__":
    main()
