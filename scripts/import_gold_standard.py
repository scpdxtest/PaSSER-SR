#!/usr/bin/env python3
"""
PaSSER-SR: Import Gold Standard Script
=======================================
Imports Gold Standard selection from JSON into MongoDB for a project.
Gold Standard papers must exist in the project's corpus.

Usage:
    python import_gold_standard.py --input gold_standard_100.json \\
        --project "EVoting-2026" \\
        --mongo mongodb://localhost:27017 --db passer_sr

Arguments:
    --input     Path to Gold Standard JSON file
    --project   Project ID (must already exist with corpus)
    --mongo     MongoDB connection string (default: mongodb://localhost:27017)
    --db        Database name (default: passer_sr)
    --clear     Clear existing Gold Standard for this project

JSON Format (Option 1 - corpus_id references):
{
    "description": "100 papers selected for Gold Standard validation",
    "selection_method": "Stratified sampling from Pool A and Pool B",
    "screening_instructions": {
        "inclusion_criteria": [
            {"code": "IC1", "description": "Proposes blockchain-based model"}
        ],
        "exclusion_criteria": [
            {"code": "EC1", "description": "Only mentions blockchain"}
        ]
    },
    "papers": [
        {
            "corpus_id": "CORP-0001",
            "pool": "A",
            "selection_reason": "High relevance score"
        }
    ]
}

JSON Format (Option 2 - full paper data, creates corpus entries if needed):
{
    "papers": [
        {
            "gs_id": "GS-001",
            "corpus_id": "CORP-0001",
            "title": "Paper title",
            "abstract": "...",
            "pool": "A"
        }
    ]
}

Author: PaSSER-SR Team
Date: January 2026
"""

import argparse
import json
import sys
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
GOLD_STANDARD_COLLECTION = "gold_standard"
DECISIONS_COLLECTION = "screening_decisions"
RESOLUTIONS_COLLECTION = "resolutions"
CONFIG_COLLECTION = "screening_config"


def import_gold_standard(input_file: str, project_id: str, mongo_uri: str,
                         db_name: str, clear_existing: bool = False) -> Dict[str, int]:
    """
    Import Gold Standard papers from JSON file to MongoDB.
    Returns statistics dict with counts.
    """
    stats = {
        "total": 0,
        "inserted": 0,
        "updated": 0,
        "errors": 0,
        "skipped": 0,
        "corpus_linked": 0,
        "corpus_created": 0
    }
    
    # Load JSON file
    print(f"\n📄 Loading Gold Standard from: {input_file}")
    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"❌ Error: File not found: {input_file}")
        return stats
    except json.JSONDecodeError as e:
        print(f"❌ Error: Invalid JSON: {e}")
        return stats
    
    papers = data.get("papers", [])
    if not papers:
        print("❌ Error: No papers found in JSON file")
        return stats
    
    stats["total"] = len(papers)
    print(f"   Found {len(papers)} Gold Standard papers")
    print(f"   Project ID: {project_id}")
    
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
    
    # Check if project exists
    project = db[PROJECTS_COLLECTION].find_one({"project_id": project_id})
    if not project:
        print(f"❌ Error: Project not found: {project_id}")
        print("   Please import corpus first using import_corpus.py")
        client.close()
        return stats
    
    print(f"   ✓ Project found: {project.get('name', project_id)}")
    print(f"   Corpus size: {project.get('corpus_count', 0)} papers")
    
    # Create indexes
    print(f"\n📁 Setting up Gold Standard collection...")
    
    db[GOLD_STANDARD_COLLECTION].create_index([
        ("project_id", ASCENDING), 
        ("gs_id", ASCENDING)
    ], unique=True)
    db[GOLD_STANDARD_COLLECTION].create_index("project_id")
    
    db[DECISIONS_COLLECTION].create_index([
        ("project_id", ASCENDING),
        ("gs_id", ASCENDING),
        ("antelope_account", ASCENDING)
    ], unique=True)
    
    db[RESOLUTIONS_COLLECTION].create_index([
        ("project_id", ASCENDING),
        ("gs_id", ASCENDING)
    ], unique=True)
    
    print("   ✓ Indexes created")
    
    # Clear existing if requested
    if clear_existing:
        print(f"\n🗑️ Clearing existing Gold Standard for project: {project_id}")
        del_gs = db[GOLD_STANDARD_COLLECTION].delete_many({"project_id": project_id})
        del_dec = db[DECISIONS_COLLECTION].delete_many({"project_id": project_id})
        del_res = db[RESOLUTIONS_COLLECTION].delete_many({"project_id": project_id})
        print(f"   Deleted: {del_gs.deleted_count} GS papers, {del_dec.deleted_count} decisions, {del_res.deleted_count} resolutions")
    
    # Get existing corpus papers for linking
    corpus_papers = {
        p["corpus_id"]: p 
        for p in db[CORPUS_COLLECTION].find(
            {"project_id": project_id},
            {"_id": 0, "corpus_id": 1, "title": 1, "abstract": 1, "year": 1, 
             "authors": 1, "doi": 1, "venue": 1, "source_name": 1, "type": 1, "url": 1, "pdf_url": 1,
             "data_sources": 1, "cited_by_count": 1, "all_keywords": 1}
        )
    }
    print(f"   Found {len(corpus_papers)} corpus papers for linking")
    
    # Import Gold Standard papers
    print(f"\n📥 Importing Gold Standard papers...")
    now = datetime.utcnow()
    gs_counter = 1
    
    for i, paper in enumerate(papers):
        # Determine gs_id
        gs_id = paper.get("gs_id")
        if not gs_id:
            gs_id = f"GS-{gs_counter:03d}"
            gs_counter += 1
        
        # Get corpus_id reference
        corpus_id = paper.get("corpus_id")
        
        # Try to link to corpus
        corpus_paper = None
        if corpus_id and corpus_id in corpus_papers:
            corpus_paper = corpus_papers[corpus_id]
            stats["corpus_linked"] += 1
        elif "title" in paper and "abstract" in paper:
            # Full paper data provided - create corpus entry if needed
            if corpus_id:
                # Create corpus entry
                corpus_doc = {
                    "project_id": project_id,
                    "corpus_id": corpus_id,
                    "title": paper.get("title", ""),
                    "abstract": paper.get("abstract", ""),
                    "year": paper.get("year"),
                    "authors": paper.get("authors", []),
                    "doi": paper.get("doi", ""),
                    "venue": paper.get("venue", "") or paper.get("source_name", ""),
                    "type": paper.get("type", ""),
                    "url": paper.get("url", ""),
                    "pdf_url": paper.get("pdf_url", ""),
                    "data_sources": paper.get("data_sources", []) or ([paper.get("data_source")] if paper.get("data_source") else []),
                    "cited_by_count": paper.get("cited_by_count", 0),
                    "imported_at": now,
                    "updated_at": now
                }
                db[CORPUS_COLLECTION].update_one(
                    {"project_id": project_id, "corpus_id": corpus_id},
                    {"$set": corpus_doc},
                    upsert=True
                )
                corpus_paper = corpus_doc
                stats["corpus_created"] += 1
            else:
                # Use paper data directly
                corpus_paper = paper
        else:
            print(f"   ⚠️ {gs_id}: No corpus link and no full data - skipping")
            stats["skipped"] += 1
            continue
        
        # Prepare Gold Standard document
        # Normalize venue: use existing venue, or source_name, or fallback to empty
        venue_value = (
            corpus_paper.get("venue") or paper.get("venue") or 
            corpus_paper.get("source_name") or paper.get("source_name") or ""
        )
        
        gs_doc = {
            "project_id": project_id,
            "gs_id": gs_id,
            "corpus_id": corpus_id or f"INLINE-{gs_id}",
            "title": corpus_paper.get("title", paper.get("title", "")),
            "abstract": corpus_paper.get("abstract", paper.get("abstract", "")),
            "year": corpus_paper.get("year", paper.get("year")),
            "authors": corpus_paper.get("authors", paper.get("authors", [])),
            "doi": corpus_paper.get("doi", paper.get("doi", "")),
            "venue": venue_value,
            "source_name": corpus_paper.get("source_name", paper.get("source_name", "")),
            "type": corpus_paper.get("type", paper.get("type", "")),
            "url": corpus_paper.get("url", paper.get("url", "")),
            "pdf_url": corpus_paper.get("pdf_url", paper.get("pdf_url", "")),
            "data_sources": corpus_paper.get("data_sources", paper.get("data_sources", [])) or ([corpus_paper.get("data_source", paper.get("data_source"))] if corpus_paper.get("data_source") or paper.get("data_source") else []),
            "cited_by_count": corpus_paper.get("cited_by_count", paper.get("cited_by_count", 0)),
            "all_keywords": corpus_paper.get("all_keywords", paper.get("all_keywords", [])),
            "pool": paper.get("pool", ""),
            "is_calibration": paper.get("is_calibration", False),  # NEW
            "selection_reason": paper.get("selection_reason", ""),
            "updated_at": now
        }
        
        try:
            result = db[GOLD_STANDARD_COLLECTION].update_one(
                {"project_id": project_id, "gs_id": gs_id},
                {
                    "$set": gs_doc,
                    "$setOnInsert": {"created_at": now}
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
            print(f"   ❌ Error importing {gs_id}: {e}")
            stats["errors"] += 1
    
    # Store screening instructions if present
    if "screening_instructions" in data:
        print(f"\n📝 Storing screening instructions...")
        db[CONFIG_COLLECTION].update_one(
            {"project_id": project_id},
            {
                "$set": {
                    "project_id": project_id,
                    "screening_instructions": data["screening_instructions"],
                    "updated_at": now
                },
                "$setOnInsert": {"created_at": now}
            },
            upsert=True
        )
        print("   ✓ Screening instructions saved")
    
    # Update project with Gold Standard count
    gs_count = db[GOLD_STANDARD_COLLECTION].count_documents({"project_id": project_id})
    db[PROJECTS_COLLECTION].update_one(
        {"project_id": project_id},
        {
            "$set": {
                "gold_standard_count": gs_count,
                "gold_standard_source": input_file,
                "updated_at": now
            }
        }
    )
    
    # Close connection
    client.close()
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 Gold Standard Import Summary:")
    print(f"   Project ID:       {project_id}")
    print(f"   Total in file:    {stats['total']}")
    print(f"   Inserted:         {stats['inserted']}")
    print(f"   Updated:          {stats['updated']}")
    print(f"   Skipped:          {stats['skipped']}")
    print(f"   Errors:           {stats['errors']}")
    print(f"   Linked to corpus: {stats['corpus_linked']}")
    print(f"   Created in corpus:{stats['corpus_created']}")
    print("=" * 60)
    
    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Import PaSSER-SR Gold Standard papers"
    )
    parser.add_argument(
        "--input", type=str, required=True,
        help="Path to Gold Standard JSON file"
    )
    parser.add_argument(
        "--project", type=str, required=True,
        help="Project ID (must exist with corpus)"
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
        help="Clear existing Gold Standard before import"
    )
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("PaSSER-SR: Import Gold Standard")
    print("=" * 60)
    
    stats = import_gold_standard(
        input_file=args.input,
        project_id=args.project,
        mongo_uri=args.mongo,
        db_name=args.db,
        clear_existing=args.clear
    )
    
    if stats["errors"] > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
