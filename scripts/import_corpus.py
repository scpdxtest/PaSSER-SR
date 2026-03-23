#!/usr/bin/env python3
"""
PaSSER-SR: Import Corpus Script
================================
Imports full paper corpus from JSON into MongoDB for a project.
This is the main dataset that will be processed by LLM screening.

Usage:
    python import_corpus.py --input corpus_evoting.json \\
        --project "EVoting-2026" --name "E-Voting Systematic Review 2026" \\
        --mongo mongodb://localhost:27017 --db passer_sr

Arguments:
    --input     Path to corpus JSON file (list of papers)
    --project   Project ID (unique identifier)
    --name      Human-readable project name
    --desc      Project description (optional)
    --mongo     MongoDB connection string (default: mongodb://localhost:27017)
    --db        Database name (default: passer_sr)
    --clear     Clear existing corpus for this project before import

JSON Format:
{
    "metadata": {
        "name": "E-Voting Corpus",
        "description": "Papers on blockchain-based e-voting",
        "search_query": "blockchain AND (voting OR election)",
        "date_range": "2015-2025",
        "sources": ["OpenAlex", "Semantic Scholar", "CORE", "arXiv", "MDPI"]
    },
    "papers": [
        {
            "corpus_id": "CORP-0001",
            "title": "Paper title",
            "abstract": "Paper abstract",
            "year": 2023,
            "authors": ["Author 1", "Author 2"],
            "doi": "10.xxxx/xxxxx",
            "venue": "Journal/Conference name",
            "url": "https://...",
            "pdf_url": "https://...",
            "data_sources": ["OpenAlex", "Semantic Scholar"],
            "cited_by_count": 15
        }
    ]
}

Author: PaSSER-SR Team
Date: January 2026
"""

import argparse
import json
import sys
import hashlib
from datetime import datetime
from typing import Dict, Any, List

try:
    from pymongo import MongoClient, ASCENDING
    from pymongo.errors import ConnectionFailure
except ImportError:
    print("Error: pymongo is required. Install with: pip install pymongo")
    sys.exit(1)


# Collection names
PROJECTS_COLLECTION = "projects"
CORPUS_COLLECTION = "corpus_papers"


def validate_paper(paper: Dict[str, Any], index: int) -> tuple:
    """Validate a single paper record."""
    if "corpus_id" not in paper and "id" not in paper:
        return False, f"Paper {index}: missing 'corpus_id' or 'id'"
    
    if "title" not in paper:
        return False, f"Paper {index}: missing 'title'"
    
    if "abstract" not in paper:
        return False, f"Paper {index}: missing 'abstract'"
    
    return True, None


def generate_corpus_id(paper: Dict, index: int) -> str:
    """Generate corpus_id if not present."""
    if "corpus_id" in paper:
        return paper["corpus_id"]
    if "id" in paper:
        return f"CORP-{paper['id']}"
    # Generate from title hash
    title_hash = hashlib.md5(paper.get("title", "").encode()).hexdigest()[:8]
    return f"CORP-{index:05d}-{title_hash}"


def import_corpus(input_file: str, project_id: str, project_name: str,
                  project_desc: str, mongo_uri: str, db_name: str,
                  clear_existing: bool = False) -> Dict[str, int]:
    """
    Import corpus papers from JSON file to MongoDB.
    Returns statistics dict with counts.
    """
    stats = {
        "total": 0,
        "inserted": 0,
        "updated": 0,
        "errors": 0,
        "skipped": 0
    }
    
    # Load JSON file
    print(f"\n📄 Loading corpus from: {input_file}")
    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"❌ Error: File not found: {input_file}")
        return stats
    except json.JSONDecodeError as e:
        print(f"❌ Error: Invalid JSON: {e}")
        return stats
    
    # Extract papers array
    papers = data.get("papers", [])
    if not papers:
        print("❌ Error: No papers found in JSON file")
        return stats
    
    metadata = data.get("metadata", {})
    
    stats["total"] = len(papers)
    print(f"   Found {len(papers)} papers")
    print(f"   Project ID: {project_id}")
    print(f"   Project Name: {project_name}")
    
    # Validate papers
    print("\n🔍 Validating papers...")
    valid_papers = []
    corpus_ids = set()
    
    for i, paper in enumerate(papers):
        is_valid, error = validate_paper(paper, i + 1)
        if not is_valid:
            print(f"   ❌ {error}")
            stats["errors"] += 1
            continue
        
        # Generate/normalize corpus_id
        corpus_id = generate_corpus_id(paper, i)
        
        if corpus_id in corpus_ids:
            print(f"   ⚠️ Duplicate corpus_id: {corpus_id}")
            stats["skipped"] += 1
            continue
        
        corpus_ids.add(corpus_id)
        paper["corpus_id"] = corpus_id
        valid_papers.append(paper)
    
    print(f"   ✓ {len(valid_papers)} valid papers")
    
    if not valid_papers:
        print("\n❌ No valid papers to import")
        return stats
    
    # Connect to MongoDB
    print(f"\n🔌 Connecting to MongoDB: {mongo_uri}")
    try:
        client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
        client.admin.command('ping')
        print("   ✓ Connected")
    except ConnectionFailure as e:
        print(f"   ❌ Connection failed: {e}")
        return stats
    
    db = client[db_name]
    
    # Create indexes
    print(f"\n📁 Setting up collections...")
    
    db[PROJECTS_COLLECTION].create_index("project_id", unique=True)
    db[CORPUS_COLLECTION].create_index([("project_id", ASCENDING), ("corpus_id", ASCENDING)], unique=True)
    db[CORPUS_COLLECTION].create_index("project_id")
    
    print("   ✓ Indexes created")
    
    # Clear existing if requested
    if clear_existing:
        print(f"\n🗑️ Clearing existing corpus for project: {project_id}")
        del_result = db[CORPUS_COLLECTION].delete_many({"project_id": project_id})
        print(f"   Deleted: {del_result.deleted_count} papers")
    
    # Create/update project record
    now = datetime.utcnow()
    
    project_doc = {
        "project_id": project_id,
        "name": project_name,
        "description": project_desc or metadata.get("description", ""),
        "status": "active",
        "corpus_count": len(valid_papers),
        "gold_standard_count": 0,  # Will be updated by import_gold_standard
        "corpus_metadata": {
            "search_query": metadata.get("search_query", ""),
            "date_range": metadata.get("date_range", ""),
            "sources": metadata.get("sources", []),
            "source_file": input_file
        },
        "updated_at": now
    }
    
    result = db[PROJECTS_COLLECTION].update_one(
        {"project_id": project_id},
        {
            "$set": project_doc,
            "$setOnInsert": {"created_at": now, "created_by": "import_script"}
        },
        upsert=True
    )
    
    if result.upserted_id:
        print(f"\n📋 New project created: {project_id}")
    else:
        print(f"\n📋 Project updated: {project_id}")
    
    # Import papers
    print(f"\n📥 Importing corpus papers...")
    
    for paper in valid_papers:
        corpus_id = paper["corpus_id"]
        
        # Normalize venue field (could be 'venue' or 'source_name')
        venue = paper.get("venue", "") or paper.get("source_name", "")
        
        # Normalize data_sources (could be array 'data_sources' or single 'data_source')
        data_sources = paper.get("data_sources", [])
        if not data_sources and paper.get("data_source"):
            data_sources = [paper.get("data_source")]
        
        doc = {
            "project_id": project_id,
            "corpus_id": corpus_id,
            "title": paper.get("title", ""),
            "abstract": paper.get("abstract", ""),
            "year": paper.get("year"),
            "authors": paper.get("authors", []),
            "doi": paper.get("doi", ""),
            "venue": venue,
            "source_name": paper.get("source_name", ""),  # Keep original source_name
            "type": paper.get("type", ""),
            "url": paper.get("url", ""),
            "pdf_url": paper.get("pdf_url", ""),
            "data_sources": data_sources,
            "cited_by_count": paper.get("cited_by_count", 0),
            "keywords": paper.get("keywords", []),
            "updated_at": now,
            # === NEW: Keyword fields ===
            "concepts": paper.get("concepts", []),
            "concept_names": paper.get("concept_names", []),
            "topics": paper.get("topics", []),
            "fields_of_study": paper.get("fields_of_study", []),
            "categories": paper.get("categories", []),
            "subjects": paper.get("subjects", []),
            "keywords": paper.get("keywords", []),
            "all_keywords": paper.get("all_keywords", []),
        }
        
        try:
            result = db[CORPUS_COLLECTION].update_one(
                {"project_id": project_id, "corpus_id": corpus_id},
                {
                    "$set": doc,
                    "$setOnInsert": {"imported_at": now}
                },
                upsert=True
            )
            
            if result.upserted_id:
                stats["inserted"] += 1
            elif result.modified_count > 0:
                stats["updated"] += 1
            else:
                stats["skipped"] += 1
                
        except Exception as e:
            print(f"   ❌ Error importing {corpus_id}: {e}")
            stats["errors"] += 1
    
    # Close connection
    client.close()
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 Corpus Import Summary:")
    print(f"   Project ID:     {project_id}")
    print(f"   Project Name:   {project_name}")
    print(f"   Total in file:  {stats['total']}")
    print(f"   Inserted:       {stats['inserted']}")
    print(f"   Updated:        {stats['updated']}")
    print(f"   Skipped:        {stats['skipped']}")
    print(f"   Errors:         {stats['errors']}")
    print("=" * 60)
    
    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Import PaSSER-SR corpus papers"
    )
    parser.add_argument(
        "--input", type=str, required=True,
        help="Path to corpus JSON file"
    )
    parser.add_argument(
        "--project", type=str, required=True,
        help="Project ID (unique identifier)"
    )
    parser.add_argument(
        "--name", type=str, required=True,
        help="Human-readable project name"
    )
    parser.add_argument(
        "--desc", type=str, default="",
        help="Project description"
    )
    parser.add_argument(
        "--mongo", type=str, default="mongodb://localhost:27017",
        help="MongoDB connection string"
    )
    parser.add_argument(
        "--db", type=str, default="passer_sr",
        help="Database name"
    )
    parser.add_argument(
        "--clear", action="store_true",
        help="Clear existing corpus before import"
    )
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("PaSSER-SR: Import Corpus")
    print("=" * 60)
    
    stats = import_corpus(
        input_file=args.input,
        project_id=args.project,
        project_name=args.name,
        project_desc=args.desc,
        mongo_uri=args.mongo,
        db_name=args.db,
        clear_existing=args.clear
    )
    
    if stats["errors"] > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
