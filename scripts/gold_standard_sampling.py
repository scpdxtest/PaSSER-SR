#!/usr/bin/env python3
"""
Gold Standard Sampling Script (Enriched Sampling)
==================================================
Paper 1: "Designing Multi-Agent LLM Strategies for Systematic Review Screening"

This script selects papers for the Gold Standard using enriched sampling:
- Pool A: Papers with electoral keywords (probably relevant)
- Pool B: Papers without electoral keywords (probably not relevant)

The selection is shuffled and anonymized so reviewers cannot identify pool membership.

Expected input format (from deduplicate.py or filter_electoral.py):
{
    "metadata": {
        "name": "Blockchain Electoral Systems Corpus",
        "sources": ["OpenAlex", "Semantic Scholar", "CORE", "arXiv", "MDPI"],
        ...
    },
    "papers": [
        {
            "corpus_id": "BES-0001",
            "title": "...",
            "abstract": "...",
            "authors": [...],
            "year": 2023,
            "data_sources": ["openalex", "semantic_scholar"],
            ...
        }
    ]
}

Methodology Reference:
- Enriched sampling is standard practice in LLM validation studies
- See: "We randomly selected 100 excluded abstracts and 100 included abstracts 
       for screening by LLM tools" (Springer 2024)
- Ensures sufficient positive examples for valid metric calculation

Outputs:
- gold_standard_<N>.json     : Papers for blind screening (NO pool info)
- gold_standard_<N>.csv      : Same data in CSV format (backup)
- sampling_mapping.json      : Pool membership mapping (FOR POST-HOC ANALYSIS ONLY)
- sampling_report.txt        : Statistics and reproducibility info
- sampling_log.txt           : Detailed execution log

Usage:
    python gold_standard_sampling.py --input filtered_corpus.json --output-dir results/gold_standard/
    python gold_standard_sampling.py --input filtered_corpus.json --pool-a-size 200 --pool-b-size 0

Author: PaSSER-SR Team
Date: February 2026
Version: 2.0
Repository: [GITHUB URL]
License: MIT
"""

import json
import csv
import random
import argparse
import re
import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Tuple, Optional

# Import screening criteria from centralized constants
from screening_criteria_constants import (
    INCLUSION_CRITERIA_TEXT,
    EXCLUSION_CRITERIA_TEXT
)


# =============================================================================
# CONFIGURATION
# =============================================================================

RANDOM_SEED = 42
POOL_A_SIZE = 200  # Papers with electoral keywords (default)
POOL_B_SIZE = 0    # Papers without electoral keywords (default: 0 for filtered corpus)

# Electoral keywords for Pool A identification
# Case-insensitive, whole-word matching in title and abstract
# These keywords indicate papers likely about public electoral processes
ELECTORAL_KEYWORDS = [
    r'\belection\b',
    r'\belections\b',
    r'\belectoral\b', 
    r'\bvoting\b',
    r'\bvote\b',
    r'\bvotes\b',
    r'\bvoter\b',
    r'\bvoters\b',
    r'\be-voting\b',
    r'\bevoting\b',
    r'\bi-voting\b',
    r'\bballot\b',
    r'\bballots\b',
    r'\bpoll\b',
    r'\bpolls\b',
    r'\bpolling\b',
    r'\breferendum\b',
    r'\breferenda\b',
    r'\bplebiscite\b',
]

# Compile regex pattern (case-insensitive)
KEYWORD_PATTERN = re.compile('|'.join(ELECTORAL_KEYWORDS), re.IGNORECASE)

# NOTE: Screening criteria are imported from screening_criteria_constants.py
# This ensures consistency across all components (LLM screening, Human screening, Gold Standard)

# Convert criteria format for this script (dict -> list of dicts)
INCLUSION_CRITERIA = [
    {"code": code, "text": text}
    for code, text in sorted(INCLUSION_CRITERIA_TEXT.items())
]

EXCLUSION_CRITERIA = [
    {"code": code, "text": text}
    for code, text in sorted(EXCLUSION_CRITERIA_TEXT.items())
]


# =============================================================================
# LOGGING SETUP
# =============================================================================

def setup_logging(log_file: Path) -> logging.Logger:
    """Configure logging to both file and console."""
    logger = logging.getLogger('gold_standard_sampling')
    logger.setLevel(logging.DEBUG)
    
    # File handler (detailed)
    fh = logging.FileHandler(log_file, encoding='utf-8')
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(message)s'))
    
    # Console handler (info only)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter('%(message)s'))
    
    logger.addHandler(fh)
    logger.addHandler(ch)
    
    return logger


# =============================================================================
# DATA LOADING AND VALIDATION
# =============================================================================

def load_corpus(filepath: str, logger: logging.Logger) -> List[Dict]:
    """
    Load the unified corpus JSON file with validation.
    
    Expected format from deduplicate.py:
    {
        "metadata": {...},
        "papers": [...]
    }
    
    Args:
        filepath: Path to unified_corpus.json
        logger: Logger instance
        
    Returns:
        List of paper dictionaries
        
    Raises:
        FileNotFoundError: If corpus file doesn't exist
        ValueError: If corpus format is invalid
    """
    logger.info(f"Loading corpus from: {filepath}")
    
    if not Path(filepath).exists():
        raise FileNotFoundError(f"Corpus file not found: {filepath}")
    
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # Handle different formats
    if isinstance(data, list):
        # Direct list of papers
        papers = data
        logger.info("Loaded corpus as direct list")
    elif isinstance(data, dict):
        # Dict with 'papers' key (standard format from deduplicate.py)
        papers = data.get('papers', [])
        
        # Log metadata if present
        metadata = data.get('metadata', {})
        if metadata:
            logger.info(f"Corpus name: {metadata.get('name', 'N/A')}")
            logger.info(f"Years covered: {metadata.get('years_covered', 'N/A')}")
            sources = metadata.get('sources', [])
            if sources:
                logger.info(f"Sources: {', '.join(sources)}")
            stats = metadata.get('statistics', {})
            if stats:
                logger.info(f"Reported statistics: {stats.get('total_papers', 'N/A')} papers")
    else:
        raise ValueError(f"Unexpected corpus format: {type(data)}")
    
    if not papers:
        raise ValueError("Corpus is empty")
    
    # Validate that papers have expected structure
    sample = papers[0]
    if 'corpus_id' not in sample:
        logger.warning("Papers don't have corpus_id - may not be from deduplicate.py")
    
    logger.info(f"Loaded {len(papers):,} papers")
    return papers


def validate_paper(paper: Dict, logger: logging.Logger) -> bool:
    """
    Validate that a paper has required fields for screening.
    
    Required:
    - title (non-empty)
    - abstract field (can be empty but must exist)
    - some identifier (corpus_id preferred, or doi, or other id)
    
    Args:
        paper: Paper dictionary
        logger: Logger instance
        
    Returns:
        True if valid, False otherwise
    """
    # Must have title
    title = paper.get('title', '')
    if not title or not title.strip():
        return False
    
    # Must have abstract field (can be empty string)
    if 'abstract' not in paper:
        return False
    
    # Must have some identifier (corpus_id is standard from deduplicate.py)
    has_id = any([
        paper.get('corpus_id'),  # Primary: from deduplicate.py (BES-XXXX)
        paper.get('doi'),
        paper.get('id'),
        paper.get('paperId'),
        paper.get('arxiv_id'),
    ])
    
    return has_id


def get_paper_id(paper: Dict) -> str:
    """
    Extract the best available identifier from a paper.
    
    Priority:
    1. corpus_id (format: BES-XXXX from deduplicate.py)
    2. DOI
    3. Other IDs (paperId from Semantic Scholar, id from OpenAlex, etc.)
    """
    # corpus_id is the canonical identifier after deduplication
    corpus_id = paper.get('corpus_id')
    if corpus_id:
        return corpus_id
    
    # Fallback to DOI
    doi = paper.get('doi')
    if doi:
        return doi
    
    # Fallback to other IDs
    return (
        paper.get('id') or 
        paper.get('paperId') or
        paper.get('arxiv_id') or
        f"unknown_{hash(paper.get('title', ''))}"
    )


# =============================================================================
# POOL PARTITIONING
# =============================================================================

def has_electoral_keywords(paper: Dict) -> Tuple[bool, List[str]]:
    """
    Check if paper contains electoral keywords in title or abstract.
    
    Args:
        paper: Paper dictionary
        
    Returns:
        Tuple of (has_keywords: bool, matched_keywords: list)
    """
    title = paper.get('title', '') or ''
    abstract = paper.get('abstract', '') or ''
    text = f"{title} {abstract}"
    
    matches = KEYWORD_PATTERN.findall(text)
    unique_matches = list(set(m.lower() for m in matches))
    
    return bool(matches), unique_matches


def partition_corpus(papers: List[Dict], logger: logging.Logger) -> Tuple[List[Dict], List[Dict]]:
    """
    Partition corpus into Pool A (with keywords) and Pool B (without keywords).
    
    Args:
        papers: List of paper dictionaries
        logger: Logger instance
        
    Returns:
        Tuple of (pool_a, pool_b)
    """
    pool_a = []  # Probably relevant (has electoral keywords)
    pool_b = []  # Probably not relevant (no electoral keywords)
    
    invalid_count = 0
    keyword_stats = {}
    
    for paper in papers:
        # Validate paper
        if not validate_paper(paper, logger):
            invalid_count += 1
            continue
        
        # Check for keywords
        has_keywords, matched = has_electoral_keywords(paper)
        
        if has_keywords:
            paper['_matched_keywords'] = matched  # Temporary field for logging
            pool_a.append(paper)
            for kw in matched:
                keyword_stats[kw] = keyword_stats.get(kw, 0) + 1
        else:
            pool_b.append(paper)
    
    # Log statistics
    logger.info(f"Partitioning complete:")
    logger.info(f"  Pool A (with keywords): {len(pool_a):,} papers")
    logger.info(f"  Pool B (no keywords): {len(pool_b):,} papers")
    logger.info(f"  Invalid papers skipped: {invalid_count}")
    
    logger.debug("Keyword frequency in Pool A:")
    for kw, count in sorted(keyword_stats.items(), key=lambda x: -x[1])[:10]:
        logger.debug(f"  {kw}: {count}")
    
    return pool_a, pool_b


# =============================================================================
# SAMPLE SELECTION
# =============================================================================

def select_sample(pool: List[Dict], n: int, pool_name: str, 
                  logger: logging.Logger) -> List[Dict]:
    """
    Randomly select n papers from a pool.
    
    Args:
        pool: List of papers
        n: Number to select
        pool_name: Name for logging
        logger: Logger instance
        
    Returns:
        List of selected papers
    """
    if n == 0:
        logger.info(f"Skipping {pool_name} (size = 0)")
        return []
    
    if len(pool) < n:
        logger.warning(f"{pool_name} has only {len(pool)} papers, need {n}")
        logger.warning(f"Selecting all {len(pool)} available papers")
        return pool.copy()
    
    selected = random.sample(pool, n)
    logger.info(f"Selected {len(selected)} papers from {pool_name}")
    
    return selected


# =============================================================================
# ANONYMIZATION
# =============================================================================

def extract_author_names(authors) -> List[str]:
    """
    Extract author names from various formats used in the corpus.
    
    Handles:
    - List of strings: ["John Smith", "Jane Doe"]
    - List of dicts with 'name': [{"name": "John Smith"}]
    - List of dicts with 'first_name'/'last_name': [{"first_name": "John", "last_name": "Smith"}]
    - List of dicts with 'display_name': [{"display_name": "John Smith"}]
    
    Returns:
        List of author name strings
    """
    if not authors:
        return []
    
    if not isinstance(authors, list):
        return []
    
    names = []
    for author in authors:
        if isinstance(author, str):
            # Already a string
            names.append(author)
        elif isinstance(author, dict):
            # Try different field names
            name = (
                author.get('name') or 
                author.get('display_name') or
                None
            )
            if not name:
                # Try first_name + last_name
                first = author.get('first_name', '') or ''
                last = author.get('last_name', '') or ''
                if first or last:
                    name = f"{first} {last}".strip()
            if name:
                names.append(name)
    
    return names


def anonymize_paper(paper: Dict, gs_id: int) -> Dict:
    """
    Create anonymized version of paper for blind screening.
    
    Removes pool membership information and internal fields.
    Keeps only fields needed for screening.
    
    Args:
        paper: Original paper dict
        gs_id: Sequential Gold Standard ID (1-N)
        
    Returns:
        Anonymized paper dictionary
    """
    # Extract authors safely (handles multiple formats)
    author_names = extract_author_names(paper.get('authors', []))
    
    # Get venue/journal (different sources use different field names)
    venue = (
        paper.get('venue') or 
        paper.get('journal') or 
        paper.get('source_name') or 
        ''
    )
    
    return {
        # Identification
        'gs_id': f"GS-{gs_id:03d}",
        'corpus_id': get_paper_id(paper),
        
        # Content for screening
        'title': (paper.get('title', '') or '').strip(),
        'abstract': (paper.get('abstract', '') or '').strip(),
        
        # Metadata (helpful but not required for decision)
        'year': paper.get('year') or paper.get('publication_year'),
        'authors': author_names[:10],  # Limit to first 10 authors
        'doi': paper.get('doi', ''),
        'venue': venue,
        'url': paper.get('url', ''),
        'pdf_url': paper.get('pdf_url', ''),
        'data_sources': paper.get('data_sources', []),
        'cited_by_count': paper.get('cited_by_count', 0),
        'all_keywords': paper.get('all_keywords', []),
        
        # Screening fields (to be filled by reviewers)
        'screener1_decision': None,
        'screener1_confidence': None,
        'screener1_reason': None,
        'screener1_timestamp': None,
        'screener2_decision': None,
        'screener2_confidence': None,
        'screener2_reason': None,
        'screener2_timestamp': None,
        'agreement': None,
        'final_decision': None,
        'resolution_reason': None,
        'resolver': None,
        'resolution_timestamp': None,
    }


def create_mapping_entry(paper: Dict, gs_id: int, pool: str) -> Dict:
    """
    Create mapping entry linking anonymized paper to pool membership.
    
    This is for POST-HOC analysis only - do not share with reviewers!
    
    Args:
        paper: Original paper dict
        gs_id: Gold Standard ID
        pool: Pool identifier ('A' or 'B')
        
    Returns:
        Mapping dictionary
    """
    return {
        'gs_id': f"GS-{gs_id:03d}",
        'corpus_id': get_paper_id(paper),
        'pool': pool,
        'matched_keywords': paper.get('_matched_keywords', []),
    }


# =============================================================================
# FILE OUTPUT
# =============================================================================

def save_json(data: Dict, filepath: Path, logger: logging.Logger) -> str:
    """Save data to JSON file and return checksum."""
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    # Calculate checksum
    with open(filepath, 'rb') as f:
        checksum = hashlib.sha256(f.read()).hexdigest()
    
    logger.info(f"Saved: {filepath}")
    logger.debug(f"  Checksum (SHA-256): {checksum}")
    
    return checksum


def save_csv(papers: List[Dict], filepath: Path, logger: logging.Logger):
    """Save papers to CSV file."""
    if not papers:
        logger.warning(f"No papers to save to CSV")
        return
    
    fieldnames = ['gs_id', 'corpus_id', 'title', 'year', 'doi', 'venue']
    
    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(papers)
    
    logger.info(f"Saved: {filepath}")


def generate_report(pool_a: List, pool_b: List, selected_a: List, selected_b: List,
                   total_papers: int, checksums: Dict, args) -> str:
    """Generate human-readable sampling report."""
    
    total_selected = len(selected_a) + len(selected_b)
    
    # Format inclusion criteria
    ic_text = "\n".join([f"  {c['code']}: {c['text']}" for c in INCLUSION_CRITERIA])
    
    # Format exclusion criteria
    ec_text = "\n".join([f"  {c['code']}: {c['text']}" for c in EXCLUSION_CRITERIA])
    
    report = f"""
================================================================================
GOLD STANDARD SAMPLING REPORT
================================================================================
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Script Version: 2.0

CONFIGURATION
-------------
Random Seed: {args.seed}
Pool A Target Size: {args.pool_a_size}
Pool B Target Size: {args.pool_b_size}
Input Corpus: {args.input}
Output Directory: {args.output_dir}

CORPUS STATISTICS
-----------------
Total papers in corpus: {total_papers:,}
Valid papers processed: {len(pool_a) + len(pool_b):,}

Pool A (with electoral keywords): {len(pool_a):,} papers ({100*len(pool_a)/(len(pool_a)+len(pool_b)):.1f}%)
Pool B (without electoral keywords): {len(pool_b):,} papers ({100*len(pool_b)/(len(pool_a)+len(pool_b)):.1f}%)

SELECTION RESULTS
-----------------
Selected from Pool A: {len(selected_a)} papers
Selected from Pool B: {len(selected_b)} papers
Total Gold Standard: {total_selected} papers

Expected class distribution after screening:
  - Pool A papers: likely ~70-90% INCLUDE
  - Pool B papers: likely ~5-20% INCLUDE
  - Overall: estimated ~30-50% INCLUDE

KEYWORDS USED FOR POOL A CLASSIFICATION
---------------------------------------
election, elections, electoral, voting, vote, votes, voter, voters, e-voting, evoting, i-voting, ballot, ballots, poll, polls, polling, referendum, referenda, plebiscite

Note: Keywords are matched as whole words, case-insensitive, 
in both title and abstract.

OUTPUT FILES
------------
1. gold_standard_{total_selected}.json  - Papers for blind screening (NO pool info)
   Checksum: {checksums.get('gold_standard', 'N/A')}

2. gold_standard_{total_selected}.csv   - Same data in CSV format (backup)

3. sampling_mapping.json   - Pool membership (POST-HOC ANALYSIS ONLY)
   Checksum: {checksums.get('mapping', 'N/A')}
   ⚠️  DO NOT share with reviewers until after screening!

4. sampling_report.txt     - This file

5. sampling_log.txt        - Detailed execution log

REPRODUCIBILITY
---------------
To reproduce this exact selection:

1. Ensure you have the same input corpus
2. Run: python gold_standard_sampling.py \\
        --input {args.input} \\
        --output-dir {args.output_dir} \\
        --seed {args.seed} \\
        --pool-a-size {args.pool_a_size} \\
        --pool-b-size {args.pool_b_size}
3. Verify checksum of gold_standard_{total_selected}.json matches:
   {checksums.get('gold_standard', 'N/A')}

INSTRUCTIONS FOR HUMAN SCREENING MODULE
---------------------------------------
1. Load gold_standard_{total_selected}.json into the screening interface
2. Create two reviewer accounts (Screener1, Screener2)
3. Enable blind mode (reviewers cannot see each other's decisions)
4. Each reviewer screens all {total_selected} papers independently
5. After both complete, calculate Cohen's Kappa
6. Resolve disagreements with a third resolver
7. Export final decisions

SCREENING DECISION OPTIONS
--------------------------
Decision values: INCLUDE / EXCLUDE / UNCERTAIN
Confidence levels: HIGH / MEDIUM / LOW

INCLUSION CRITERIA (paper must meet IC1 + IC2, and at least one of IC3/IC4/IC5):
{ic_text}

EXCLUSION CRITERIA (any one excludes):
{ec_text}

NEXT STEPS
----------
[ ] 1. Load gold_standard_{total_selected}.json into Human Screening Module
[ ] 2. Calibration: Both reviewers screen 10 papers together
[ ] 3. Blind screening: Each reviewer screens {total_selected} papers independently  
[ ] 4. Calculate Cohen's Kappa (target: κ ≥ 0.60)
[ ] 5. Resolve disagreements
[ ] 6. Export final Gold Standard
[ ] 7. Use for LLM strategy evaluation

================================================================================
END OF REPORT
================================================================================
"""
    return report


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Gold Standard Sampling using Enriched Sampling method',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python gold_standard_sampling.py --input filtered_corpus.json
  python gold_standard_sampling.py --input data/corpus.json --output-dir results/gs/
  python gold_standard_sampling.py --seed 123 --pool-a-size 200 --pool-b-size 0
        """
    )
    parser.add_argument(
        '--input', '-i',
        type=str,
        default='results/filtered_corpus.json',
        help='Path to corpus JSON file (unified or filtered)'
    )
    parser.add_argument(
        '--output-dir', '-o', 
        type=str,
        default='results/gold_standard/',
        help='Output directory for all generated files'
    )
    parser.add_argument(
        '--seed', '-s',
        type=int,
        default=RANDOM_SEED,
        help=f'Random seed for reproducibility (default: {RANDOM_SEED})'
    )
    parser.add_argument(
        '--pool-a-size',
        type=int,
        default=POOL_A_SIZE,
        help=f'Papers to select from Pool A (default: {POOL_A_SIZE})'
    )
    parser.add_argument(
        '--pool-b-size',
        type=int,
        default=POOL_B_SIZE,
        help=f'Papers to select from Pool B (default: {POOL_B_SIZE})'
    )
    
    args = parser.parse_args()
    
    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Setup logging
    log_file = output_dir / 'sampling_log.txt'
    logger = setup_logging(log_file)
    
    logger.info("=" * 60)
    logger.info("GOLD STANDARD SAMPLING - START")
    logger.info("=" * 60)
    
    # Set random seed
    random.seed(args.seed)
    logger.info(f"Random seed: {args.seed}")
    
    # Load corpus
    papers = load_corpus(args.input, logger)
    total_papers = len(papers)
    
    # Partition into pools
    logger.info("Partitioning corpus by keyword presence...")
    pool_a, pool_b = partition_corpus(papers, logger)
    
    # Validate pool sizes (allow 0 for pool_b)
    if args.pool_a_size > 0 and len(pool_a) < args.pool_a_size:
        logger.error(f"Pool A too small: {len(pool_a)} < {args.pool_a_size}")
        raise ValueError("Insufficient papers in Pool A")
    
    if args.pool_b_size > 0 and len(pool_b) < args.pool_b_size:
        logger.error(f"Pool B too small: {len(pool_b)} < {args.pool_b_size}")
        raise ValueError("Insufficient papers in Pool B")
    
    # Select samples
    logger.info("Selecting random samples...")
    selected_a = select_sample(pool_a, args.pool_a_size, "Pool A", logger)
    selected_b = select_sample(pool_b, args.pool_b_size, "Pool B", logger)
    
    # Combine and shuffle
    logger.info("Combining and shuffling...")
    combined = []
    for paper in selected_a:
        combined.append((paper, 'A'))
    for paper in selected_b:
        combined.append((paper, 'B'))
    
    random.shuffle(combined)
    
    # Create anonymized gold standard and mapping
    logger.info("Creating anonymized gold standard...")
    gold_standard = []
    mapping = []
    
    for i, (paper, pool) in enumerate(combined, 1):
        gold_standard.append(anonymize_paper(paper, i))
        mapping.append(create_mapping_entry(paper, i, pool))
    
    # Prepare output data
    timestamp = datetime.now().isoformat()
    total_selected = len(gold_standard)
    
    # Format criteria for JSON output
    ic_formatted = [f"{c['code']}: {c['text']}" for c in INCLUSION_CRITERIA]
    ec_formatted = [f"{c['code']}: {c['text']}" for c in EXCLUSION_CRITERIA]
    
    gs_output = {
        'metadata': {
            'name': 'Gold Standard for LLM Screening Evaluation',
            'description': f'Enriched sample of {total_selected} papers for inter-rater reliability testing',
            'project': 'Blockchain Models for Electoral Process - Systematic Review',
            'paper': 'Paper 1: Multi-Agent LLM Strategies for Screening',
            'created_at': timestamp,
            'random_seed': args.seed,
            'total_papers': total_selected,
            'source_corpus': args.input,
            'source_corpus_size': total_papers,
            'note': 'Pool membership is hidden - see sampling_mapping.json for post-hoc analysis'
        },
        'screening_instructions': {
            'decisions': ['INCLUDE', 'EXCLUDE', 'UNCERTAIN'],
            'confidence_levels': ['HIGH', 'MEDIUM', 'LOW'],
            'inclusion_criteria': ic_formatted,
            'exclusion_criteria': ec_formatted
        },
        'papers': gold_standard
    }
    
    mapping_output = {
        'metadata': {
            'name': 'Gold Standard Pool Mapping',
            'description': 'Maps papers to source pools - FOR POST-HOC ANALYSIS ONLY',
            'warning': 'DO NOT share with reviewers until after blind screening is complete',
            'created_at': timestamp,
            'random_seed': args.seed,
            'pool_a_description': 'Papers containing electoral keywords',
            'pool_b_description': 'Papers without electoral keywords',
            'pool_a_selected': len(selected_a),
            'pool_b_selected': len(selected_b),
            'keywords_used': [k.replace('\\b', '') for k in ELECTORAL_KEYWORDS],
        },
        'mapping': mapping
    }
    
    # Save outputs with dynamic filename
    checksums = {}
    
    gs_filename = f'gold_standard_{total_selected}.json'
    csv_filename = f'gold_standard_{total_selected}.csv'
    
    checksums['gold_standard'] = save_json(
        gs_output, 
        output_dir / gs_filename,
        logger
    )
    
    checksums['mapping'] = save_json(
        mapping_output,
        output_dir / 'sampling_mapping.json', 
        logger
    )
    
    save_csv(gold_standard, output_dir / csv_filename, logger)
    
    # Generate and save report
    report = generate_report(
        pool_a, pool_b, selected_a, selected_b,
        total_papers, checksums, args
    )
    
    report_path = output_dir / 'sampling_report.txt'
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report)
    logger.info(f"Saved: {report_path}")
    
    # Final summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("GOLD STANDARD SAMPLING - COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Total papers selected: {total_selected}")
    logger.info(f"  From Pool A (keywords): {len(selected_a)}")
    logger.info(f"  From Pool B (no keywords): {len(selected_b)}")
    logger.info("")
    logger.info("Output files:")
    logger.info(f"  {output_dir / gs_filename}")
    logger.info(f"  {output_dir / csv_filename}")
    logger.info(f"  {output_dir / 'sampling_mapping.json'} (POST-HOC ONLY)")
    logger.info(f"  {output_dir / 'sampling_report.txt'}")
    logger.info(f"  {output_dir / 'sampling_log.txt'}")
    logger.info("")
    logger.info("⚠️  IMPORTANT: Do not share sampling_mapping.json with reviewers!")
    logger.info("=" * 60)


if __name__ == '__main__':
    main()
