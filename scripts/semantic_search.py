#!/usr/bin/env python3
"""
Semantic Scholar Search Script for Blockchain Electoral Systems Corpus
Project: PaSSER-SR (Systematic Review)
Author: PaSSER-SR Team

Note: Semantic Scholar API has rate limits (100 requests/5 min without API key)
For higher limits, register at https://www.semanticscholar.org/product/api
"""

import requests
import json
import time
import os
from datetime import datetime
from typing import List, Dict, Optional

# Configuration
OUTPUT_DIR = "results"
OUTPUT_FILE = "semantic_results.json"
API_BASE = "https://api.semanticscholar.org/graph/v1/paper/search"
API_KEY = None  # Optional: Add your API key for higher rate limits

# Search terms (same as other scripts)
GROUP_A = ["blockchain", "distributed ledger", "DLT", "smart contract"]
GROUP_B = ["voting", "election", "e-voting", "electoral", "ballot", "referendum"]

EXCLUDE_TERMS = ["DAO voting", "governance voting", "token voting", "opinion poll"]


def build_search_queries() -> List[str]:
    """
    Build multiple search queries for Semantic Scholar.
    SS works better with simpler queries, so we split into combinations.
    """
    queries = []
    # Main combinations
    for a_term in ["blockchain", "distributed ledger", "smart contract"]:
        for b_term in ["voting", "election", "e-voting", "electoral"]:
            queries.append(f"{a_term} {b_term}")
    return queries


def fetch_semantic_scholar(
    query: str,
    year_range: str = "2015-2025",
    limit: int = 100,
    offset: int = 0
) -> Dict:
    """
    Fetch results from Semantic Scholar API.
    
    Args:
        query: Search query string
        year_range: Year range filter (e.g., "2015-2025")
        limit: Results per request (max 100)
        offset: Pagination offset
    
    Returns:
        API response dictionary
    """
    headers = {}
    if API_KEY:
        headers["x-api-key"] = API_KEY
    
    params = {
        "query": query,
        "year": year_range,
        "limit": limit,
        "offset": offset,
        "fields": "paperId,externalIds,title,abstract,authors,year,venue,citationCount,url,publicationTypes,fieldsOfStudy,s2FieldsOfStudy"
    }
    
    try:
        response = requests.get(API_BASE, params=params, headers=headers, timeout=30)
        
        # Handle rate limiting
        if response.status_code == 429:
            print("Rate limited. Waiting 60 seconds...")
            time.sleep(60)
            return fetch_semantic_scholar(query, year_range, limit, offset)
        
        response.raise_for_status()
        return response.json()
        
    except requests.exceptions.RequestException as e:
        print(f"Error: {e}")
        return {"data": [], "total": 0}


def fetch_all_results(queries: List[str], max_per_query: int = 500) -> List[Dict]:
    """
    Fetch results for all query combinations.
    
    Args:
        queries: List of search queries
        max_per_query: Maximum results per query
    
    Returns:
        Combined list of results
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
            data = fetch_semantic_scholar(
                query=query,
                year_range="2015-2025",
                limit=100,
                offset=offset
            )
            
            papers = data.get("data", [])
            if not papers:
                break
            
            # Deduplicate by paperId
            new_papers = []
            for paper in papers:
                paper_id = paper.get("paperId")
                if paper_id and paper_id not in seen_ids:
                    seen_ids.add(paper_id)
                    new_papers.append(paper)
            
            all_results.extend(new_papers)
            query_results += len(new_papers)
            
            print(f"  Offset {offset}: {len(new_papers)} new papers (total unique: {len(all_results)})")
            
            # Check if we've reached the end
            total = data.get("total", 0)
            if offset + 100 >= total:
                break
            
            offset += 100
            
            # Rate limiting - be respectful
            time.sleep(1.0)  # 1 second between requests
        
        print(f"  Query total: {query_results} papers")
        
        # Longer pause between queries
        time.sleep(2.0)
    
    return all_results


def normalize_result(paper: Dict) -> Dict:
    """
    Normalize Semantic Scholar paper to unified corpus format.
    """
    # Extract DOI from externalIds
    external_ids = paper.get("externalIds", {}) or {}
    doi = external_ids.get("DOI", "")
    
    # Extract authors
    authors = []
    for author in paper.get("authors", []) or []:
        name = author.get("name", "")
        if name:
            authors.append(name)
    
    # === NEW: Extract fields of study ===
    # fieldsOfStudy: Simple list of field names
    fields_of_study_simple = paper.get("fieldsOfStudy", []) or []
    
    # s2FieldsOfStudy: More detailed with source info
    s2_fields_raw = paper.get("s2FieldsOfStudy", []) or []
    s2_fields = [
        {
            "category": f.get("category", ""),
            "source": f.get("source", "")
        }
        for f in s2_fields_raw
        if f.get("category")
    ]
    
    # Combined unique list of all field names
    all_fields = list(set(
        fields_of_study_simple + 
        [f["category"] for f in s2_fields]
    ))
    
    return {
        "id": paper.get("paperId", ""),
        "doi": doi,
        "title": paper.get("title", ""),
        "abstract": paper.get("abstract", ""),
        "authors": authors,
        "year": paper.get("year"),
        "type": paper.get("publicationTypes", ["unknown"])[0] if paper.get("publicationTypes") else "unknown",
        "source_name": paper.get("venue", ""),
        "cited_by_count": paper.get("citationCount", 0),
        "url": f"https://www.semanticscholar.org/paper/{paper.get('paperId', '')}",
        "data_source": "semantic_scholar",
        "fetched_at": datetime.now().isoformat(),
        # === NEW FIELDS ===
        "fields_of_study": fields_of_study_simple,
        "s2_fields_of_study": s2_fields,
        "all_keywords": all_fields
    }


def should_exclude(result: Dict) -> bool:
    """Check if result should be excluded."""
    title = (result.get("title") or "").lower()
    abstract = (result.get("abstract") or "").lower()
    combined = title + " " + abstract
    
    # Check for DAO/governance context without election context
    election_terms = ["election", "electoral", "ballot", "referendum", "voter"]
    has_election_context = any(et in combined for et in election_terms)
    
    if "dao" in combined and "voting" in combined and not has_election_context:
        return True
    if "governance voting" in combined and not has_election_context:
        return True
    if "token voting" in combined and not has_election_context:
        return True
    
    return False


def save_results(results: List[Dict], output_path: str):
    """Save results to JSON file."""
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({
            "metadata": {
                "source": "Semantic Scholar",
                "query_date": datetime.now().isoformat(),
                "total_results": len(results),
                "years": "2015-2025",
                "note": "Multiple query combinations used"
            },
            "results": results
        }, f, indent=2, ensure_ascii=False)
    
    print(f"Saved {len(results)} results to {output_path}")


def main():
    """Main execution function."""
    print("=" * 60)
    print("Semantic Scholar Search for Blockchain Electoral Systems")
    print("=" * 60)
    
    # Build queries
    queries = build_search_queries()
    print(f"\nGenerated {len(queries)} search queries")
    
    # Fetch results
    raw_results = fetch_all_results(queries, max_per_query=500)
    
    # Normalize results
    print("\nNormalizing results...")
    normalized = [normalize_result(paper) for paper in raw_results]
    
    # Filter out excluded terms
    print("Filtering excluded terms...")
    filtered = [r for r in normalized if not should_exclude(r)]
    print(f"After exclusion filter: {len(filtered)} (removed {len(normalized) - len(filtered)})")
    
    # Filter out results without abstract
    with_abstract = [r for r in filtered if r.get("abstract")]
    print(f"With abstract: {len(with_abstract)} (removed {len(filtered) - len(with_abstract)})")
    
    # Save results
    output_path = os.path.join(OUTPUT_DIR, OUTPUT_FILE)
    save_results(with_abstract, output_path)
    
    # Print summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total unique papers: {len(raw_results)}")
    print(f"After filtering: {len(with_abstract)}")
    print(f"Output file: {output_path}")


if __name__ == "__main__":
    main()
