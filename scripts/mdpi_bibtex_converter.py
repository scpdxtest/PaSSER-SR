#!/usr/bin/env python3
"""
MDPI BibTeX Converter for Blockchain Electoral Systems Corpus
Project: PaSSER-SR (Systematic Review)

MDPI blocks automated requests. This script converts
a manually exported BibTeX file from MDPI to JSON format.

Instructions:
1. Go to https://www.mdpi.com/search
2. Search: blockchain voting
3. Filter: 2015-2025
4. Select all results
5. Export -> BibTeX
6. Repeat for: blockchain election, blockchain e-voting, etc.
7. Merge all .bib files into one: mdpi_export.bib
8. Run this script: python mdpi_bibtex_converter.py
"""

import re
import json
import os
from datetime import datetime
from typing import List, Dict, Optional

# Configuration
INPUT_FILE = "mdpi_export.bib"  # Combined BibTeX file from manual export
OUTPUT_DIR = "results"
OUTPUT_FILE = "mdpi_results.json"

EXCLUDE_TERMS = ["DAO voting", "governance voting", "token voting"]


def parse_bibtex_file(filepath: str) -> List[Dict]:
    """
    Parse BibTeX file and extract entries.
    
    Args:
        filepath: Path to .bib file
    
    Returns:
        List of parsed entry dictionaries
    """
    if not os.path.exists(filepath):
        print(f"⚠️  File not found: {filepath}")
        print(f"\nPlease follow the instructions:")
        print("1. Go to https://www.mdpi.com/search")
        print("2. Search: blockchain voting (and other combinations)")
        print("3. Export -> BibTeX")
        print(f"4. Save as: {filepath}")
        return []
    
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    
    # Split into entries
    entries = []
    
    # Pattern to match BibTeX entries
    entry_pattern = r'@(\w+)\{([^,]+),\s*(.*?)\n\}'
    
    # More robust parsing - split by @ and process each entry
    raw_entries = re.split(r'\n@', content)
    
    for i, raw_entry in enumerate(raw_entries):
        if i == 0 and not raw_entry.strip().startswith('@'):
            # First chunk might not have @
            if not raw_entry.strip():
                continue
            raw_entry = '@' + raw_entry if not raw_entry.startswith('@') else raw_entry
        else:
            raw_entry = '@' + raw_entry
        
        entry = parse_bibtex_entry(raw_entry.strip())
        if entry:
            entries.append(entry)
    
    return entries


def parse_bibtex_entry(entry_text: str) -> Optional[Dict]:
    """
    Parse a single BibTeX entry.
    
    Args:
        entry_text: Raw BibTeX entry text
    
    Returns:
        Dictionary with parsed fields or None
    """
    if not entry_text or not entry_text.startswith('@'):
        return None
    
    # Extract entry type and key
    header_match = re.match(r'@(\w+)\{([^,]+),', entry_text)
    if not header_match:
        return None
    
    entry_type = header_match.group(1).lower()
    entry_key = header_match.group(2).strip()
    
    # Extract fields
    fields = {}
    
    # Pattern for field = {value} or field = "value"
    field_pattern = r'(\w+)\s*=\s*[{"](.+?)[}"](?:,|\s*\})'
    
    # More flexible pattern for multi-line values
    for match in re.finditer(r'(\w+)\s*=\s*\{([^}]+)\}', entry_text, re.DOTALL):
        field_name = match.group(1).lower()
        field_value = match.group(2).strip()
        # Clean up whitespace
        field_value = re.sub(r'\s+', ' ', field_value)
        fields[field_name] = field_value
    
    if not fields.get('title'):
        return None
    
    return {
        "entry_type": entry_type,
        "entry_key": entry_key,
        "fields": fields
    }


def normalize_result(entry: Dict) -> Dict:
    """
    Normalize BibTeX entry to unified corpus format.
    """
    fields = entry.get("fields", {})
    
    # Parse authors
    authors_raw = fields.get("author", "")
    authors = []
    if authors_raw:
        # BibTeX uses "and" to separate authors
        author_parts = re.split(r'\s+and\s+', authors_raw)
        for author in author_parts:
            # Clean up author name (remove braces, extra spaces)
            author = re.sub(r'[{}]', '', author).strip()
            if author:
                authors.append(author)
    
    # Parse year
    year = None
    year_str = fields.get("year", "")
    if year_str:
        try:
            year = int(year_str)
        except:
            pass
    
    # Get DOI
    doi = fields.get("doi", "")
    if doi.startswith("https://doi.org/"):
        doi = doi.replace("https://doi.org/", "")
    
    # Build URL if not present
    url = fields.get("url", "")
    if not url and doi:
        url = f"https://doi.org/{doi}"
    
    return {
        "id": entry.get("entry_key", ""),
        "doi": doi,
        "title": fields.get("title", "").replace("{", "").replace("}", ""),
        "abstract": fields.get("abstract", ""),
        "authors": authors,
        "year": year,
        "type": "article",
        "source_name": fields.get("journal", "MDPI"),
        "volume": fields.get("volume", ""),
        "number": fields.get("number", ""),
        "pages": fields.get("pages", ""),
        "cited_by_count": 0,
        "url": url,
        "keywords": fields.get("keywords", "").split(";") if fields.get("keywords") else [],
        "data_source": "mdpi",
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
                "source": "MDPI",
                "query_date": datetime.now().isoformat(),
                "total_results": len(results),
                "years": "2015-2025",
                "note": "Converted from manual BibTeX export"
            },
            "results": results
        }, f, indent=2, ensure_ascii=False)
    
    print(f"Saved {len(results)} results to {output_path}")


def main():
    """Main execution function."""
    print("=" * 60)
    print("MDPI BibTeX Converter")
    print("=" * 60)
    
    # Parse BibTeX file
    print(f"\nReading: {INPUT_FILE}")
    entries = parse_bibtex_file(INPUT_FILE)
    
    if not entries:
        return
    
    print(f"Parsed {len(entries)} BibTeX entries")
    
    # Normalize results
    print("\nNormalizing results...")
    normalized = [normalize_result(entry) for entry in entries]
    
    # Filter by year
    print("Filtering by year (2015-2025)...")
    year_filtered = filter_by_year(normalized)
    print(f"After year filter: {len(year_filtered)}")
    
    # Filter out excluded terms
    print("Filtering excluded terms...")
    filtered = [r for r in year_filtered if not should_exclude(r)]
    print(f"After exclusion filter: {len(filtered)}")
    
    # Remove duplicates by DOI
    seen_dois = set()
    unique = []
    for r in filtered:
        doi = r.get("doi", "")
        if doi:
            if doi not in seen_dois:
                seen_dois.add(doi)
                unique.append(r)
        else:
            unique.append(r)
    print(f"After deduplication: {len(unique)}")
    
    # Filter out results without abstract (optional - comment out if abstracts not in BibTeX)
    # with_abstract = [r for r in unique if r.get("abstract")]
    # print(f"With abstract: {len(with_abstract)}")
    
    # Save results
    output_path = os.path.join(OUTPUT_DIR, OUTPUT_FILE)
    save_results(unique, output_path)
    
    # Print summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total BibTeX entries: {len(entries)}")
    print(f"After all filters: {len(unique)}")
    print(f"Output file: {output_path}")
    
    # Show sample
    if unique:
        print("\nSample entry:")
        sample = unique[0]
        print(f"  Title: {sample['title'][:60]}...")
        print(f"  DOI: {sample['doi']}")
        print(f"  Year: {sample['year']}")
        print(f"  Authors: {', '.join(sample['authors'][:2])}...")


if __name__ == "__main__":
    main()
