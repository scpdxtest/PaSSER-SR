#!/usr/bin/env python3
"""
PaSSER-SR: Filter Corpus by Electoral Context
==============================================
Filters the unified corpus to keep only papers with electoral context.
This removes generic "blockchain voting" papers that are not about elections.

Usage:
    python filter_electoral.py --input unified_corpus.json --output filtered_corpus.json

Author: PaSSER-SR Team
Date: February 2026
"""

import json
import argparse
import os
import re
from datetime import datetime
from typing import List, Dict

# Electoral keywords - must have at least one in title or abstract
# These are specific to electoral/political voting, not generic voting
ELECTORAL_KEYWORDS = [
    # Core electoral terms
    "election",
    "elections",
    "electoral",
    "e-voting",
    "evoting",
    "e-vote",
    "i-voting",
    "internet voting",
    "online voting",
    "electronic voting",
    "remote voting",
    
    # Voting infrastructure
    "ballot",
    "ballots",
    "ballot box",
    "polling station",
    "polling place",
    "vote counting",
    "vote tallying",
    "voter registration",
    "voter verification",
    "voter authentication",
    "voter privacy",
    "voter anonymity",
    
    # Political terms
    "referendum",
    "referenda",
    "plebiscite",
    "democracy",
    "democratic",
    "suffrage",
    "enfranchisement",
    
    # Actors
    "voter",
    "voters",
    "electorate",
    "candidate",
    "candidates",
    "political party",
    "election commission",
    "election authority",
    "election official",
    
    # Specific voting types
    "parliamentary",
    "presidential",
    "municipal",
    "local election",
    "national election",
    "general election",
    "primary election",
    "by-election",
    "midterm",
]

# Terms that indicate NON-electoral voting (for reporting)
NON_ELECTORAL_INDICATORS = [
    "dao voting",
    "governance voting",
    "governance token",
    "token voting",
    "consensus voting",
    "validator voting",
    "staking",
    "proof of stake",
    "delegated voting",  # in blockchain context
    "liquid democracy",  # often about DAOs
    "quadratic voting",  # often theoretical/DAO
]


def normalize_text(text: str) -> str:
    """Normalize text for keyword matching."""
    if not text:
        return ""
    # Lowercase and normalize whitespace
    text = text.lower()
    text = re.sub(r'\s+', ' ', text)
    return text


def has_electoral_context(paper: Dict) -> bool:
    """
    Check if paper has electoral context based on keywords.
    
    Args:
        paper: Paper dictionary with title and abstract
        
    Returns:
        True if paper contains electoral keywords
    """
    title = normalize_text(paper.get("title", ""))
    abstract = normalize_text(paper.get("abstract", ""))
    combined = title + " " + abstract
    
    for keyword in ELECTORAL_KEYWORDS:
        if keyword.lower() in combined:
            return True
    
    return False


def get_matched_keywords(paper: Dict) -> List[str]:
    """Get list of electoral keywords found in paper."""
    title = normalize_text(paper.get("title", ""))
    abstract = normalize_text(paper.get("abstract", ""))
    combined = title + " " + abstract
    
    matched = []
    for keyword in ELECTORAL_KEYWORDS:
        if keyword.lower() in combined:
            matched.append(keyword)
    
    return matched


def get_non_electoral_indicators(paper: Dict) -> List[str]:
    """Get list of non-electoral indicators found in paper."""
    title = normalize_text(paper.get("title", ""))
    abstract = normalize_text(paper.get("abstract", ""))
    combined = title + " " + abstract
    
    matched = []
    for indicator in NON_ELECTORAL_INDICATORS:
        if indicator.lower() in combined:
            matched.append(indicator)
    
    return matched


def filter_corpus(input_file: str, output_file: str, 
                  save_rejected: bool = True,
                  add_metadata: bool = True) -> Dict:
    """
    Filter corpus to keep only papers with electoral context.
    
    Args:
        input_file: Path to unified corpus JSON
        output_file: Path to save filtered corpus
        save_rejected: If True, also save rejected papers
        add_metadata: If True, add matched_keywords to each paper
        
    Returns:
        Statistics dictionary
    """
    stats = {
        "total_input": 0,
        "accepted": 0,
        "rejected": 0,
        "acceptance_rate": 0.0,
        "top_matched_keywords": {},
        "top_rejection_reasons": {}
    }
    
    # Load corpus
    print(f"\n📄 Loading corpus: {input_file}")
    with open(input_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # Handle both formats: {papers: [...]} or [...]
    if isinstance(data, dict):
        papers = data.get("papers", [])
        metadata = data.get("metadata", {})
    else:
        papers = data
        metadata = {}
    
    stats["total_input"] = len(papers)
    print(f"   Found {len(papers)} papers")
    
    # Filter papers
    print(f"\n🔍 Filtering by electoral context...")
    
    accepted_papers = []
    rejected_papers = []
    keyword_counts = {}
    rejection_reasons = {}
    
    for paper in papers:
        if has_electoral_context(paper):
            # Accepted
            if add_metadata:
                matched = get_matched_keywords(paper)
                paper["electoral_keywords_matched"] = matched
                for kw in matched:
                    keyword_counts[kw] = keyword_counts.get(kw, 0) + 1
            
            accepted_papers.append(paper)
        else:
            # Rejected
            non_electoral = get_non_electoral_indicators(paper)
            if add_metadata:
                paper["rejection_indicators"] = non_electoral if non_electoral else ["no_electoral_keywords"]
            
            for indicator in (non_electoral or ["no_electoral_keywords"]):
                rejection_reasons[indicator] = rejection_reasons.get(indicator, 0) + 1
            
            rejected_papers.append(paper)
    
    stats["accepted"] = len(accepted_papers)
    stats["rejected"] = len(rejected_papers)
    stats["acceptance_rate"] = round(len(accepted_papers) / len(papers) * 100, 1) if papers else 0
    stats["top_matched_keywords"] = dict(sorted(keyword_counts.items(), key=lambda x: -x[1])[:20])
    stats["top_rejection_reasons"] = dict(sorted(rejection_reasons.items(), key=lambda x: -x[1])[:10])
    
    # Reassign corpus IDs (sequential)
    print(f"\n🔢 Reassigning corpus IDs...")
    for i, paper in enumerate(accepted_papers, 1):
        paper["original_corpus_id"] = paper.get("corpus_id", "")
        paper["corpus_id"] = f"BES-{i:04d}"
    
    # Save filtered corpus
    print(f"\n💾 Saving filtered corpus: {output_file}")
    
    output_data = {
        "metadata": {
            **metadata,
            "filtered_at": datetime.now().isoformat(),
            "filter_type": "electoral_context",
            "original_count": stats["total_input"],
            "filtered_count": stats["accepted"],
            "acceptance_rate": f"{stats['acceptance_rate']}%",
            "electoral_keywords_used": len(ELECTORAL_KEYWORDS)
        },
        "papers": accepted_papers
    }
    
    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    
    print(f"   ✓ Saved {len(accepted_papers)} papers")
    
    # Save rejected papers if requested
    if save_rejected:
        rejected_file = output_file.replace(".json", "_rejected.json")
        print(f"\n💾 Saving rejected papers: {rejected_file}")
        
        rejected_data = {
            "metadata": {
                "description": "Papers rejected by electoral context filter",
                "filtered_at": datetime.now().isoformat(),
                "total_rejected": len(rejected_papers)
            },
            "papers": rejected_papers
        }
        
        with open(rejected_file, 'w', encoding='utf-8') as f:
            json.dump(rejected_data, f, indent=2, ensure_ascii=False)
        
        print(f"   ✓ Saved {len(rejected_papers)} rejected papers")
    
    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Filter corpus by electoral context"
    )
    parser.add_argument(
        "--input", "-i", required=True,
        help="Input unified corpus JSON file"
    )
    parser.add_argument(
        "--output", "-o", required=True,
        help="Output filtered corpus JSON file"
    )
    parser.add_argument(
        "--no-rejected", action="store_true",
        help="Don't save rejected papers to separate file"
    )
    parser.add_argument(
        "--no-metadata", action="store_true",
        help="Don't add matched keywords to papers"
    )
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("PaSSER-SR: Electoral Context Filter")
    print("=" * 60)
    
    stats = filter_corpus(
        input_file=args.input,
        output_file=args.output,
        save_rejected=not args.no_rejected,
        add_metadata=not args.no_metadata
    )
    
    # Print summary
    print("\n" + "=" * 60)
    print("📊 FILTER SUMMARY")
    print("=" * 60)
    print(f"   Total input papers:  {stats['total_input']}")
    print(f"   Accepted (electoral): {stats['accepted']}")
    print(f"   Rejected:            {stats['rejected']}")
    print(f"   Acceptance rate:     {stats['acceptance_rate']}%")
    
    print(f"\n   Top matched electoral keywords:")
    for kw, count in list(stats['top_matched_keywords'].items())[:10]:
        print(f"      {kw}: {count}")
    
    print(f"\n   Top rejection reasons:")
    for reason, count in list(stats['top_rejection_reasons'].items())[:5]:
        print(f"      {reason}: {count}")
    
    print("=" * 60)
    print("✓ Filtering complete!")


if __name__ == "__main__":
    main()
