#!/usr/bin/env python3
"""
MDPI Search Script for Blockchain Electoral Systems Corpus
Project: PaSSER-SR (Systematic Review)
Author: PaSSER-SR Team

MDPI does not have a public API, but offers:
1. RSS feeds for each journal
2. Structured XML for articles
3. Export capability via the web interface

This script uses MDPI's search endpoint and parses the results.
For more complete results, it can be combined with manual searching.
"""

import requests
import json
import time
import os
import re
from datetime import datetime
from typing import List, Dict, Optional
from bs4 import BeautifulSoup
from urllib.parse import urlencode, quote

# Configuration
OUTPUT_DIR = "results"
OUTPUT_FILE = "mdpi_results.json"

# MDPI journals relevant to blockchain/voting research
RELEVANT_JOURNALS = [
    "electronics",
    "applsci",      # Applied Sciences
    "futureinternet",
    "information",
    "computers",
    "systems",
    "algorithms",
    "cryptography",
    "jcp",          # Journal of Cybersecurity and Privacy
    "bdcc",         # Big Data and Cognitive Computing
]

# Search queries
SEARCH_QUERIES = [
    "blockchain voting",
    "blockchain election",
    "blockchain e-voting",
    "distributed ledger voting",
    "smart contract voting",
    "blockchain electoral",
    "decentralized voting"
]

EXCLUDE_TERMS = ["DAO voting", "governance voting", "token voting"]


def search_mdpi(query: str, page: int = 1, per_page: int = 20) -> Dict:
    """
    Search MDPI using their search endpoint.
    
    Args:
        query: Search query
        page: Page number
        per_page: Results per page
    
    Returns:
        Dictionary with results
    """
    # MDPI search URL
    base_url = "https://www.mdpi.com/search"
    
    params = {
        "q": query,
        "page_no": page,
        "page_count": per_page,
        "year_from": 2015,
        "year_to": 2025,
        "sort": "relevance",
        "view": "default"
    }
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5"
    }
    
    try:
        url = f"{base_url}?{urlencode(params)}"
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        
        return {
            "html": response.text,
            "status": "success"
        }
        
    except requests.exceptions.RequestException as e:
        print(f"Error searching MDPI: {e}")
        return {"html": "", "status": "error", "error": str(e)}


def parse_search_results(html: str) -> List[Dict]:
    """
    Parse MDPI search results HTML.
    
    Args:
        html: HTML content from search page
    
    Returns:
        List of parsed article dictionaries
    """
    if not html:
        return []
    
    soup = BeautifulSoup(html, 'html.parser')
    articles = []
    
    # Find article entries (MDPI uses specific class structure)
    article_divs = soup.find_all('div', class_='article-content')
    
    for div in article_divs:
        try:
            article = parse_article_div(div)
            if article:
                articles.append(article)
        except Exception as e:
            print(f"Error parsing article: {e}")
            continue
    
    return articles


def parse_article_div(div) -> Optional[Dict]:
    """Parse a single article div from MDPI search results."""
    
    # Get title and link
    title_elem = div.find('a', class_='title-link')
    if not title_elem:
        return None
    
    title = title_elem.get_text(strip=True)
    article_url = title_elem.get('href', '')
    if article_url and not article_url.startswith('http'):
        article_url = f"https://www.mdpi.com{article_url}"
    
    # Extract DOI from URL (MDPI format: /journal/volume/issue/article_number)
    doi = ""
    doi_match = re.search(r'/(\d+)/(\d+)/(\d+)$', article_url)
    if doi_match:
        # MDPI DOIs follow pattern: 10.3390/journalVolumeIssueArticle
        pass  # Will fetch from article page
    
    # Get authors
    authors_elem = div.find('div', class_='authors')
    authors = []
    if authors_elem:
        author_links = authors_elem.find_all('a')
        authors = [a.get_text(strip=True) for a in author_links if a.get_text(strip=True)]
    
    # Get journal and year
    journal_elem = div.find('a', class_='journal-name')
    journal = journal_elem.get_text(strip=True) if journal_elem else ""
    
    # Get publication info (contains year)
    pub_info = div.find('div', class_='pub-info')
    year = None
    if pub_info:
        year_match = re.search(r'20[1-2][0-9]', pub_info.get_text())
        if year_match:
            year = int(year_match.group())
    
    # Get abstract snippet (if available)
    abstract_elem = div.find('div', class_='abstract-full')
    abstract = ""
    if abstract_elem:
        abstract = abstract_elem.get_text(strip=True)
    
    return {
        "title": title,
        "url": article_url,
        "authors": authors,
        "journal": journal,
        "year": year,
        "abstract_snippet": abstract
    }


def fetch_article_details(url: str) -> Dict:
    """
    Fetch full article details from MDPI article page.
    
    Args:
        url: Article URL
    
    Returns:
        Dictionary with article details
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Get DOI
        doi = ""
        doi_elem = soup.find('meta', attrs={'name': 'citation_doi'})
        if doi_elem:
            doi = doi_elem.get('content', '')
        
        # Get full abstract
        abstract = ""
        abstract_div = soup.find('div', class_='art-abstract')
        if abstract_div:
            # Remove "Abstract" heading if present
            for heading in abstract_div.find_all(['h2', 'h3']):
                heading.decompose()
            abstract = abstract_div.get_text(strip=True)
        
        # Get keywords
        keywords = []
        keywords_div = soup.find('div', class_='art-keywords')
        if keywords_div:
            keyword_spans = keywords_div.find_all('a')
            keywords = [k.get_text(strip=True) for k in keyword_spans]
        
        # Get citation count (if available)
        cited_by = 0
        cited_elem = soup.find('span', class_='cited-by-count')
        if cited_elem:
            try:
                cited_by = int(re.search(r'\d+', cited_elem.get_text()).group())
            except:
                pass
        
        return {
            "doi": doi,
            "abstract": abstract,
            "keywords": keywords,
            "cited_by_count": cited_by
        }
        
    except Exception as e:
        print(f"Error fetching article details: {e}")
        return {}


def fetch_all_results(queries: List[str], max_per_query: int = 100) -> List[Dict]:
    """
    Fetch results for all queries with deduplication.
    """
    all_results = []
    seen_urls = set()
    
    print(f"Running {len(queries)} search queries...")
    print("-" * 50)
    
    for i, query in enumerate(queries, 1):
        print(f"\n[{i}/{len(queries)}] Query: {query}")
        
        page = 1
        query_results = 0
        
        while query_results < max_per_query:
            data = search_mdpi(query=query, page=page)
            
            if data.get("status") != "success":
                break
            
            articles = parse_search_results(data.get("html", ""))
            
            if not articles:
                break
            
            # Deduplicate by URL
            new_articles = []
            for article in articles:
                url = article.get("url")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    new_articles.append(article)
            
            all_results.extend(new_articles)
            query_results += len(new_articles)
            
            print(f"  Page {page}: {len(new_articles)} new papers (total unique: {len(all_results)})")
            
            if len(articles) < 20:  # Less than full page means no more results
                break
            
            page += 1
            time.sleep(2.0)  # Be respectful to MDPI servers
        
        print(f"  Query total: {query_results} papers")
        time.sleep(3.0)
    
    return all_results


def enrich_with_details(articles: List[Dict], max_to_enrich: int = 200) -> List[Dict]:
    """
    Enrich articles with full details (DOI, abstract) from article pages.
    Only enriches articles that don't have full abstract.
    """
    print(f"\nEnriching articles with full details...")
    
    enriched = 0
    for i, article in enumerate(articles):
        if enriched >= max_to_enrich:
            print(f"  Reached max enrichment limit ({max_to_enrich})")
            break
        
        # Skip if already has good abstract
        if article.get("abstract") and len(article.get("abstract", "")) > 200:
            continue
        
        url = article.get("url")
        if not url:
            continue
        
        print(f"  [{enriched + 1}/{max_to_enrich}] Fetching: {article.get('title', '')[:50]}...")
        
        details = fetch_article_details(url)
        
        if details:
            article["doi"] = details.get("doi", article.get("doi", ""))
            article["abstract"] = details.get("abstract", article.get("abstract_snippet", ""))
            article["keywords"] = details.get("keywords", [])
            article["cited_by_count"] = details.get("cited_by_count", 0)
            enriched += 1
        
        time.sleep(1.5)  # Rate limiting
    
    print(f"  Enriched {enriched} articles")
    return articles


def normalize_result(article: Dict) -> Dict:
    """
    Normalize MDPI article to unified corpus format.
    """
    # Clean DOI
    doi = article.get("doi", "")
    if doi.startswith("https://doi.org/"):
        doi = doi.replace("https://doi.org/", "")
    
    return {
        "id": doi or article.get("url", ""),
        "doi": doi,
        "title": article.get("title", ""),
        "abstract": article.get("abstract", article.get("abstract_snippet", "")),
        "authors": article.get("authors", []),
        "year": article.get("year"),
        "type": "article",
        "source_name": article.get("journal", "MDPI"),
        "cited_by_count": article.get("cited_by_count", 0),
        "url": article.get("url", ""),
        "keywords": article.get("keywords", []),
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
                "note": "Open access publisher - all papers freely available"
            },
            "results": results
        }, f, indent=2, ensure_ascii=False)
    
    print(f"Saved {len(results)} results to {output_path}")


def main():
    """Main execution function."""
    print("=" * 60)
    print("MDPI Search for Blockchain Electoral Systems")
    print("=" * 60)
    
    # Check for BeautifulSoup
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        print("\n⚠️  BeautifulSoup not installed!")
        print("Run: pip install beautifulsoup4")
        return
    
    # Fetch results
    raw_results = fetch_all_results(SEARCH_QUERIES, max_per_query=100)
    
    if not raw_results:
        print("\nNo results found. This might be due to:")
        print("1. MDPI website structure changed")
        print("2. Network issues")
        print("\nAlternative: Use manual search at https://www.mdpi.com/search")
        print("Export results as BibTeX and convert to JSON")
        return
    
    # Enrich with full details
    enriched = enrich_with_details(raw_results, max_to_enrich=200)
    
    # Normalize results
    print("\nNormalizing results...")
    normalized = [normalize_result(article) for article in enriched]
    
    # Filter out excluded terms
    print("Filtering excluded terms...")
    filtered = [r for r in normalized if not should_exclude(r)]
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
    print(f"Total papers found: {len(raw_results)}")
    print(f"After all filters: {len(with_abstract)}")
    print(f"Output file: {output_path}")
    
    # Show journals distribution
    if with_abstract:
        journals = {}
        for r in with_abstract:
            j = r.get("source_name", "Unknown")
            journals[j] = journals.get(j, 0) + 1
        
        print("\nPapers by journal:")
        for journal, count in sorted(journals.items(), key=lambda x: -x[1])[:10]:
            print(f"  {journal}: {count}")


if __name__ == "__main__":
    main()
