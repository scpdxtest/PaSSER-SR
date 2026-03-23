#!/usr/bin/env python3
"""
PaSSER-SR Screening API (v4.0 with Blockchain Audit)
====================================================
FastAPI backend for Human Screening Module operations.
Supports full corpus + gold standard per project + blockchain audit trail.

Port: 9901

Project Endpoints:
    GET  /api/projects                      - List all projects
    GET  /api/projects/{project_id}         - Get project details with stats
    POST /api/projects                      - Create new project (admin)
    PUT  /api/projects/{project_id}         - Update project (admin)

Corpus Endpoints:
    GET  /api/corpus                         - List corpus papers (paginated)
    GET  /api/corpus/{corpus_id}             - Get single corpus paper
    GET  /api/corpus/stats                   - Get corpus statistics

Gold Standard / Screening Endpoints:
    GET  /api/papers                         - List GS papers for screening
    GET  /api/papers/{gs_id}                 - Get single GS paper
    POST /api/papers/{gs_id}/decision        - Submit screening decision
    GET  /api/disagreements                  - List disagreements (resolver)
    POST /api/papers/{gs_id}/resolve         - Submit resolution (resolver)
    GET  /api/stats                          - Get screening statistics (admin)
    GET  /api/export                         - Export results (admin)

Blockchain Audit Endpoints:
    GET  /api/audit/status                   - Get audit status
    POST /api/audit/export                   - Create audit export with Merkle root
    POST /api/audit/timestamp                - Submit to OpenTimestamps
    GET  /api/audit/proof/{export_id}        - Download OTS proof
    POST /api/audit/verify                   - Verify file against stored hash

Author: PaSSER-SR Team
Date: January 2026
Version: 4.0
"""

import os
import json
import hashlib
import argparse
import base64
import subprocess
import tempfile
from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

from pymongo import MongoClient
from pymongo.errors import ConnectionFailure

import pyntelope

# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017/")
DEFAULT_DB_NAME = os.environ.get("DB_NAME", "passer_sr")
DEFAULT_BC_ENDPOINT = os.environ.get("BC_ENDPOINT", "http://localhost:8033")
DEFAULT_BC_CONTRACT = "sraudit"
DEFAULT_BC_PRIVATE_KEY = os.environ.get("BC_PRIVATE_KEY", "<YOUR_BLOCKCHAIN_PRIVATE_KEY>")
OTS_CLIENT_PATH = os.environ.get("OTS_CLIENT_PATH", "ots")  # opentimestamps-client

# Collection names
USERS_COLLECTION = "users"
PROJECTS_COLLECTION = "projects"
CORPUS_COLLECTION = "corpus_papers"
GOLD_STANDARD_COLLECTION = "gold_standard"
DECISIONS_COLLECTION = "screening_decisions"
RESOLUTIONS_COLLECTION = "resolutions"
CONFIG_COLLECTION = "screening_config"
AUDIT_EXPORTS_COLLECTION = "audit_exports"
LLM_DECISIONS_COLLECTION = "llm_decisions"
LLM_JOBS_COLLECTION = "llm_jobs"

# =============================================================================
# ENUMS AND MODELS
# =============================================================================

class ProjectStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    ARCHIVED = "archived"

class Decision(str, Enum):
    INCLUDE = "INCLUDE"
    EXCLUDE = "EXCLUDE"
    UNCERTAIN = "UNCERTAIN"

class Confidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"

class OTSStatus(str, Enum):
    NOT_TIMESTAMPED = "not_timestamped"
    PENDING = "pending"
    CONFIRMED = "confirmed"

class ProjectCreate(BaseModel):
    project_id: str = Field(..., min_length=3, max_length=50)
    name: str = Field(..., min_length=3, max_length=200)
    description: str = ""

class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[ProjectStatus] = None

class DecisionRequest(BaseModel):
    decision: Decision
    confidence: Confidence
    reason: str = Field(..., min_length=5, max_length=3000)

class ResolutionRequest(BaseModel):
    final_decision: Decision
    confidence: Confidence
    resolution_reason: str = Field(..., min_length=5, max_length=3000)

class AuditExportRequest(BaseModel):
    milestone: Optional[str] = None
    include_llm_decisions: Optional[bool] = True
    inclusion_list_job_id: Optional[str] = None

class TimestampRequest(BaseModel):
    export_id: str

class VerifyRequest(BaseModel):
    file_content: str
    filename: str

class FewShotToggleRequest(BaseModel):
    is_calibration: bool

# =============================================================================
# APPLICATION
# =============================================================================

app = FastAPI(
    title="PaSSER-SR Screening API",
    description="API for Human Screening Module with Corpus, Gold Standard & Blockchain Audit support",
    version="4.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global state
mongo_client = None
db = None
bc_endpoint = DEFAULT_BC_ENDPOINT
bc_private_key = DEFAULT_BC_PRIVATE_KEY

# =============================================================================
# STARTUP/SHUTDOWN EVENTS
# =============================================================================

@app.on_event("startup")
async def startup_event():
    """Initialize database connection on startup."""
    global db, bc_endpoint, bc_private_key
    
    # Get configuration from environment or use defaults
    mongo_uri = os.environ.get("MONGO_URI", DEFAULT_MONGO_URI)
    db_name = os.environ.get("DB_NAME", DEFAULT_DB_NAME)
    bc_endpoint = os.environ.get("BC_ENDPOINT", DEFAULT_BC_ENDPOINT)
    bc_private_key = os.environ.get("BC_PRIVATE_KEY", DEFAULT_BC_PRIVATE_KEY)
    
    # Connect to MongoDB
    if not connect_to_mongodb(mongo_uri, db_name):
        print("⚠️ WARNING: Failed to connect to MongoDB on startup")
    else:
        print(f"✓ FastAPI startup complete - Database connected")

@app.on_event("shutdown")
async def shutdown_event():
    """Close database connection on shutdown."""
    global mongo_client
    if mongo_client:
        mongo_client.close()
        print("✓ Database connection closed")

# =============================================================================
# DATABASE
# =============================================================================

def get_db():
    global db
    if db is None:
        raise HTTPException(status_code=500, detail="Database not connected")
    return db

def connect_to_mongodb(uri: str, db_name: str):
    global mongo_client, db
    try:
        mongo_client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        mongo_client.admin.command('ping')
        db = mongo_client[db_name]
        print(f"✓ Connected to MongoDB: {uri}, database: {db_name}")
        return True
    except ConnectionFailure as e:
        print(f"✗ Failed to connect to MongoDB: {e}")
        return False

# =============================================================================
# BLOCKCHAIN
# =============================================================================

def log_to_blockchain(action: str, data: Dict) -> Optional[str]:
    global bc_endpoint, bc_private_key
    if not bc_private_key:
        print("⚠️ Blockchain key not configured")
        return None
    
    try:
        data_str = json.dumps(data, sort_keys=True)
        data_hash = hashlib.sha256(data_str.encode()).hexdigest()[:16]
        
        if action == "logdecision":
            tx_data = [
                pyntelope.Data(name="screener", value=pyntelope.types.Name(data["screener"])),
                pyntelope.Data(name="projectid", value=pyntelope.types.String(data["project_id"][:32])),
                pyntelope.Data(name="gsid", value=pyntelope.types.String(data["gs_id"][:16])),
                pyntelope.Data(name="decision", value=pyntelope.types.String(data["decision"])),
                pyntelope.Data(name="confidence", value=pyntelope.types.String(data["confidence"])),
                pyntelope.Data(name="datahash", value=pyntelope.types.String(data_hash)),
            ]
        elif action == "logres":
            tx_data = [
                pyntelope.Data(name="resolver", value=pyntelope.types.Name(data["resolver"])),
                pyntelope.Data(name="projectid", value=pyntelope.types.String(data["project_id"][:32])),
                pyntelope.Data(name="gsid", value=pyntelope.types.String(data["gs_id"][:16])),
                pyntelope.Data(name="decision", value=pyntelope.types.String(data["final_decision"])),
                pyntelope.Data(name="datahash", value=pyntelope.types.String(data_hash)),
            ]
        elif action == "logexport":
            tx_data = [
                pyntelope.Data(name="admin", value=pyntelope.types.Name(data["admin"])),
                pyntelope.Data(name="projectid", value=pyntelope.types.String(data["project_id"][:32])),
                pyntelope.Data(name="destination", value=pyntelope.types.String(data.get("destination", "audit_export")[:128])),
                pyntelope.Data(name="count", value=pyntelope.types.Uint32(data.get("count", 0))),
                pyntelope.Data(name="datahash", value=pyntelope.types.String(data.get("datahash", "")[:64])),
            ]
        elif action == "logaudit":
            tx_data = [
                pyntelope.Data(name="admin", value=pyntelope.types.Name(data["admin"])),
                pyntelope.Data(name="projectid", value=pyntelope.types.String(data["project_id"][:32])),
                pyntelope.Data(name="milestone", value=pyntelope.types.String(data["milestone"][:32])),
                pyntelope.Data(name="merkleroot", value=pyntelope.types.String(data["merkle_root"][:64])),
                pyntelope.Data(name="filehash", value=pyntelope.types.String(data["file_hash"][:64])),
                pyntelope.Data(name="leafcount", value=pyntelope.types.Uint32(data["leaf_count"])),
            ]
        else:
            return None
        
        auth = pyntelope.Authorization(actor=DEFAULT_BC_CONTRACT, permission="active")
        bc_action = pyntelope.Action(account=DEFAULT_BC_CONTRACT, name=action, data=tx_data, authorization=[auth])
        raw_transaction = pyntelope.Transaction(actions=[bc_action])
        net = pyntelope.Net(host=bc_endpoint)
        linked_transaction = raw_transaction.link(net=net)
        signed_transaction = linked_transaction.sign(key=bc_private_key)
        resp = signed_transaction.send()
        
        print('traceBC', resp)
        tx_id = (
            resp.get("transaction_id")
            or (resp.get("processed") or {}).get("id")
            or "unknown"
        )
        print(f"✓ Blockchain tx: {tx_id}")
        return tx_id
        
    except Exception as e:
        print(f"✗ Blockchain error: {e}")
        return None

# =============================================================================
# MERKLE TREE FUNCTIONS
# =============================================================================

def compute_sha256(data: str) -> str:
    """Compute SHA-256 hash of a string."""
    return hashlib.sha256(data.encode('utf-8')).hexdigest()

def compute_merkle_root(hashes: List[str]) -> str:
    """
    Compute Merkle root from a list of hashes.
    If the number of hashes is odd, duplicate the last one.
    """
def compute_merkle_root(hashes: List[str]) -> str:
    """
    Compute Merkle root from a list of hashes.
    Handles empty lists and odd numbers of hashes.
    """
    # Handle empty list
    if not hashes:
        return compute_sha256("")
    
    # Single hash is its own root
    if len(hashes) == 1:
        return hashes[0]
    
    # Ensure even number of hashes by duplicating last
    if len(hashes) % 2 == 1:
        hashes.append(hashes[-1])
    
    # Build tree level by level
    while len(hashes) > 1:
        new_level = []
        for i in range(0, len(hashes), 2):
            # Safety check to prevent index errors
            if i + 1 < len(hashes):
                combined = hashes[i] + hashes[i + 1]
                new_level.append(compute_sha256(combined))
            else:
                # Odd number in this level, duplicate last
                new_level.append(hashes[i])
        hashes = new_level
    
    return hashes[0]

def build_merkle_tree(items: List[Dict]) -> Dict:
    """
    Build a Merkle tree from a list of items.
    Returns the root and the leaf hashes.
    Handles empty item lists gracefully.
    """
    if not items:
        empty_root = compute_sha256("")
        return {"root": empty_root, "leaves": [], "count": 0}
    
    # Create leaf hashes from items
    leaves = []
    for item in items:
        try:
            item_str = json.dumps(item, sort_keys=True, default=str)
            leaf_hash = compute_sha256(item_str)
            leaves.append(leaf_hash)
        except Exception as e:
            print(f"[MERKLE] Warning: Failed to hash item: {e}")
            continue
    
    # Handle case where all items failed to hash
    if not leaves:
        empty_root = compute_sha256("")
        return {"root": empty_root, "leaves": [], "count": 0}
    
    root = compute_merkle_root(leaves.copy())
    
    return {
        "root": root,
        "leaves": leaves,
        "count": len(leaves)
    }

# =============================================================================
# OPENTIMESTAMPS FUNCTIONS
# =============================================================================

def submit_to_opentimestamps(file_path: str) -> Optional[str]:
    """
    Submit a file to OpenTimestamps.
    Returns the path to the .ots proof file.
    """
    try:
        ots_file = f"{file_path}.ots"
        result = subprocess.run(
            [OTS_CLIENT_PATH, 'stamp', file_path],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode == 0 and os.path.exists(ots_file):
            print(f"✓ OpenTimestamps: Created {ots_file}")
            return ots_file
        else:
            print(f"✗ OpenTimestamps error: {result.stderr}")
            return None
            
    except FileNotFoundError:
        print(f"✗ OpenTimestamps client not found: {OTS_CLIENT_PATH}")
        return None
    except subprocess.TimeoutExpired:
        print("✗ OpenTimestamps: Timeout")
        return None
    except Exception as e:
        print(f"✗ OpenTimestamps error: {e}")
        return None

def verify_opentimestamps(ots_file: str) -> Dict:
    """
    Verify an OpenTimestamps proof.
    Returns verification status.
    """
    try:
        # First try upgrading the proof to get Bitcoin attestation
        print(f"  🔎 Running: ots upgrade {ots_file}")
        upgrade_result = subprocess.run(
            [OTS_CLIENT_PATH, 'upgrade', ots_file],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        upgrade_output = upgrade_result.stdout + "\n" + upgrade_result.stderr
        print(f"  📋 OTS UPGRADE OUTPUT:\n{upgrade_output}")
        
        # Now check 'ots info' to see the proof structure
        print(f"  🔎 Running: ots info {ots_file}")
        info_result = subprocess.run(
            [OTS_CLIENT_PATH, 'info', ots_file],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        info_output = info_result.stdout + "\n" + info_result.stderr
        print(f"  📋 OTS INFO OUTPUT:\n{info_output}")
        
        # Check if proof contains Bitcoin attestation (not PendingAttestation)
        if "Bitcoin block" in info_output and "BitcoinBlockHeaderAttestation" in info_output:
            # Extract block number if possible
            import re
            block_match = re.search(r'Bitcoin block (\d+)', info_output)
            block_num = block_match.group(1) if block_match else "unknown"
            return {
                "status": "confirmed",
                "message": f"Timestamp confirmed in Bitcoin block {block_num}"
            }
        
        # Check if still pending
        if "PendingAttestation" in info_output:
            return {
                "status": "pending",
                "message": "Timestamp submitted to calendar servers, awaiting Bitcoin confirmation"
            }
        
        # Fallback: try verify command
        print(f"  🔎 Running: ots verify {ots_file}")
        result = subprocess.run(
            [OTS_CLIENT_PATH, 'verify', ots_file],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        full_output = result.stdout + "\n" + result.stderr
        
        # Check if timestamp is confirmed on Bitcoin blockchain
        if "Bitcoin" in full_output and "attests" in full_output:
            return {
                "status": "confirmed",
                "message": result.stdout.strip()
            }
        else:
            return {
                "status": "pending",
                "message": "Timestamp pending Bitcoin confirmation"
            }
            
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }

# =============================================================================
# HELPERS
# =============================================================================

def get_user_info(db, antelope_account: str) -> Optional[Dict]:
    user = db[USERS_COLLECTION].find_one(
        {"antelope_account": antelope_account, "active": True},
        {"_id": 0}
    )
    if user:
        if "role" in user and "roles" not in user:
            user["roles"] = [user["role"]]
        elif "roles" not in user:
            user["roles"] = []
    return user

def check_roles(db, antelope_account: str, required_roles: List[str]) -> Dict:
    user = get_user_info(db, antelope_account)
    if not user:
        raise HTTPException(status_code=404, detail=f"User not found: {antelope_account}")
    
    user_roles = set(user.get("roles", []))
    if not user_roles.intersection(set(required_roles)):
        raise HTTPException(status_code=403, detail=f"Access denied. Required: {required_roles}")
    return user

def get_project(db, project_id: str) -> Dict:
    project = db[PROJECTS_COLLECTION].find_one({"project_id": project_id}, {"_id": 0})
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    return project

def calculate_cohens_kappa(db, project_id: str) -> Dict:
    pipeline = [
        {"$match": {"project_id": project_id}},
        {"$group": {
            "_id": "$gs_id",
            "decisions": {"$push": {"user": "$antelope_account", "decision": "$decision"}}
        }},
        {"$match": {"decisions.1": {"$exists": True}}}
    ]
    
    results = list(db[DECISIONS_COLLECTION].aggregate(pipeline))
    
    if len(results) < 2:
        return {"n": len(results), "kappa": None, "message": "Not enough data"}
    
    agreements = 0
    total = 0
    matrix = {d1: {d2: 0 for d2 in ["INCLUDE", "EXCLUDE", "UNCERTAIN"]} 
              for d1 in ["INCLUDE", "EXCLUDE", "UNCERTAIN"]}
    
    for item in results:
        if len(item["decisions"]) >= 2:
            d1 = item["decisions"][0]["decision"]
            d2 = item["decisions"][1]["decision"]
            matrix[d1][d2] += 1
            total += 1
            if d1 == d2:
                agreements += 1
    
    if total == 0:
        return {"n": 0, "kappa": None, "message": "No paired decisions"}
    
    Po = agreements / total
    Pe = sum(sum(matrix[d].values()) * sum(matrix[d2][d] for d2 in matrix) 
             for d in matrix) / (total * total)
    
    kappa = 0 if Pe >= 1 else (Po - Pe) / (1 - Pe)
    
    interpretation = (
        "Poor" if kappa < 0.20 else
        "Fair" if kappa < 0.40 else
        "Moderate" if kappa < 0.60 else
        "Substantial" if kappa < 0.80 else
        "Almost Perfect"
    )
    
    pabak = 2 * Po - 1
    
    pabak_interpretation = (
        "Poor" if pabak < 0.20 else
        "Fair" if pabak < 0.40 else
        "Moderate" if pabak < 0.60 else
        "Substantial" if pabak < 0.80 else
        "Almost Perfect"
    )
    
    return {
        "n": total,
        "agreements": agreements,
        "observed_agreement": round(Po, 4),
        "expected_agreement": round(Pe, 4),
        "cohens_kappa": round(kappa, 4),
        "interpretation": interpretation,
        "pabak": round(pabak, 4),
        "pabak_interpretation": pabak_interpretation
    }

def generate_export_id() -> str:
    """Generate a unique export ID."""
    import uuid
    return f"exp_{uuid.uuid4().hex[:12]}"

# =============================================================================
# HEALTH ENDPOINT
# =============================================================================

@app.get("/api/health")
async def health_check():
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "database": "connected" if db is not None else "disconnected",
        "version": "4.0.0"
    }

# =============================================================================
# USER ENDPOINTS
# =============================================================================

@app.get("/api/user/{antelope_account}")
async def get_user(antelope_account: str):
    database = get_db()
    user = get_user_info(database, antelope_account)
    if not user:
        raise HTTPException(status_code=404, detail=f"User not found: {antelope_account}")
    return user

# =============================================================================
# PROJECT ENDPOINTS
# =============================================================================

@app.get("/api/projects")
async def list_projects(
    antelope_account: str = Query(...),
    status: Optional[str] = Query(None)
):
    database = get_db()
    user = check_roles(database, antelope_account, ["screener", "resolver", "admin"])
    
    query = {}
    if status:
        query["status"] = status
    
    projects = list(database[PROJECTS_COLLECTION].find(query, {"_id": 0}).sort("created_at", -1))
    
    for project in projects:
        pid = project["project_id"]
        gs_count = database[GOLD_STANDARD_COLLECTION].count_documents({"project_id": pid})
        user_decisions = database[DECISIONS_COLLECTION].count_documents({
            "project_id": pid,
            "antelope_account": antelope_account
        })
        
        project["stats"] = {
            "corpus_count": project.get("corpus_count", 0),
            "gold_standard_count": gs_count,
            "my_completed": user_decisions
        }
    
    return {
        "projects": projects,
        "total": len(projects),
        "user_roles": user.get("roles", [])
    }

@app.get("/api/projects/{project_id}")
async def get_project_details(
    project_id: str,
    antelope_account: str = Query(...)
):
    database = get_db()
    user = check_roles(database, antelope_account, ["screener", "resolver", "admin"])
    project = get_project(database, project_id)
    
    corpus_count = database[CORPUS_COLLECTION].count_documents({"project_id": project_id})
    gs_count = database[GOLD_STANDARD_COLLECTION].count_documents({"project_id": project_id})
    
    pool_stats = list(database[GOLD_STANDARD_COLLECTION].aggregate([
        {"$match": {"project_id": project_id}},
        {"$group": {"_id": "$pool", "count": {"$sum": 1}}}
    ]))
    
    user_stats_pipeline = [
        {"$match": {"project_id": project_id}},
        {"$group": {
            "_id": "$antelope_account",
            "total": {"$sum": 1},
            "include": {"$sum": {"$cond": [{"$eq": ["$decision", "INCLUDE"]}, 1, 0]}},
            "exclude": {"$sum": {"$cond": [{"$eq": ["$decision", "EXCLUDE"]}, 1, 0]}},
            "uncertain": {"$sum": {"$cond": [{"$eq": ["$decision", "UNCERTAIN"]}, 1, 0]}}
        }}
    ]
    screener_stats = {item["_id"]: item for item in database[DECISIONS_COLLECTION].aggregate(user_stats_pipeline)}
    
    kappa_stats = calculate_cohens_kappa(database, project_id)
    resolutions_count = database[RESOLUTIONS_COLLECTION].count_documents({"project_id": project_id})
    config = database[CONFIG_COLLECTION].find_one({"project_id": project_id}, {"_id": 0})
    
    return {
        **project,
        "statistics": {
            "corpus_count": corpus_count,
            "gold_standard_count": gs_count,
            "pool_distribution": {p["_id"]: p["count"] for p in pool_stats if p["_id"]},
            "screeners": screener_stats,
            "agreement": kappa_stats,
            "resolutions": resolutions_count
        },
        "screening_instructions": config.get("screening_instructions") if config else None,
        "user_roles": user.get("roles", [])
    }

@app.post("/api/projects")
async def create_project(
    project: ProjectCreate,
    antelope_account: str = Query(...)
):
    database = get_db()
    check_roles(database, antelope_account, ["admin"])
    
    existing = database[PROJECTS_COLLECTION].find_one({"project_id": project.project_id})
    if existing:
        raise HTTPException(status_code=400, detail=f"Project exists: {project.project_id}")
    
    now = datetime.utcnow()
    project_doc = {
        "project_id": project.project_id,
        "name": project.name,
        "description": project.description,
        "status": "active",
        "corpus_count": 0,
        "gold_standard_count": 0,
        "created_by": antelope_account,
        "created_at": now,
        "updated_at": now
    }
    
    database[PROJECTS_COLLECTION].insert_one(project_doc)
    return {"success": True, "project_id": project.project_id}

@app.put("/api/projects/{project_id}")
async def update_project(
    project_id: str,
    update: ProjectUpdate,
    antelope_account: str = Query(...)
):
    database = get_db()
    check_roles(database, antelope_account, ["admin"])
    get_project(database, project_id)
    
    update_doc = {"updated_at": datetime.utcnow()}
    if update.name is not None:
        update_doc["name"] = update.name
    if update.description is not None:
        update_doc["description"] = update.description
    if update.status is not None:
        update_doc["status"] = update.status.value
    
    database[PROJECTS_COLLECTION].update_one({"project_id": project_id}, {"$set": update_doc})
    return {"success": True, "project_id": project_id}

# =============================================================================
# CORPUS ENDPOINTS
# =============================================================================

@app.get("/api/corpus")
async def list_corpus(
    project_id: str = Query(...),
    antelope_account: str = Query(...),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=10, le=100),
    search: Optional[str] = Query(None)
):
    database = get_db()
    check_roles(database, antelope_account, ["screener", "resolver", "admin"])
    get_project(database, project_id)
    
    query = {"project_id": project_id}
    if search:
        query["$or"] = [
            {"title": {"$regex": search, "$options": "i"}},
            {"abstract": {"$regex": search, "$options": "i"}}
        ]
    
    total = database[CORPUS_COLLECTION].count_documents(query)
    skip = (page - 1) * page_size
    
    papers = list(database[CORPUS_COLLECTION].find(
        query,
        {"_id": 0, "corpus_id": 1, "title": 1, "year": 1, "venue": 1, "doi": 1, "cited_by_count": 1}
    ).sort("corpus_id", 1).skip(skip).limit(page_size))
    
    return {
        "project_id": project_id,
        "papers": papers,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size
    }

@app.get("/api/corpus/{corpus_id}")
async def get_corpus_paper(
    corpus_id: str,
    project_id: str = Query(...),
    antelope_account: str = Query(...)
):
    database = get_db()
    check_roles(database, antelope_account, ["screener", "resolver", "admin"])
    
    paper = database[CORPUS_COLLECTION].find_one(
        {"project_id": project_id, "corpus_id": corpus_id},
        {"_id": 0}
    )
    if not paper:
        raise HTTPException(status_code=404, detail=f"Corpus paper not found: {corpus_id}")
    
    return paper

# =============================================================================
# GOLD STANDARD / SCREENING ENDPOINTS
# =============================================================================

@app.get("/api/papers")
async def list_papers(
    project_id: str = Query(...),
    antelope_account: str = Query(...)
):
    database = get_db()
    user = check_roles(database, antelope_account, ["screener", "resolver", "admin"])
    get_project(database, project_id)
    
    papers = list(database[GOLD_STANDARD_COLLECTION].find(
        {"project_id": project_id},
        {"_id": 0, "gs_id": 1, "title": 1, "year": 1, "pool": 1, "is_calibration": 1, 
         "venue": 1, "source_name": 1, "type": 1, "data_sources": 1, "doi": 1, "authors": 1, "all_keywords": 1}
    ).sort("gs_id", 1))
    
    # Get current user's decisions for "my_decision" field
    user_decisions = {d["gs_id"]: d["decision"] for d in database[DECISIONS_COLLECTION].find(
        {"project_id": project_id, "antelope_account": antelope_account},
        {"_id": 0, "gs_id": 1, "decision": 1}
    )}
    
    # Get all decisions (from any user) to determine if paper has been screened
    all_decisions = {d["gs_id"] for d in database[DECISIONS_COLLECTION].find(
        {"project_id": project_id},
        {"_id": 0, "gs_id": 1}
    )}
    
    for paper in papers:
        paper["my_decision"] = user_decisions.get(paper["gs_id"])
        # Status is "completed" if ANY user has screened it
        paper["status"] = "completed" if paper["gs_id"] in all_decisions else "pending"
    
    total = len(papers)
    completed = len([p for p in papers if p["status"] == "completed"])
    
    return {
        "project_id": project_id,
        "papers": papers,
        "stats": {
            "total": total,
            "completed": completed,
            "pending": total - completed
        },
        "user_roles": user.get("roles", [])
    }

@app.get("/api/papers/{gs_id}")
async def get_paper(
    gs_id: str,
    project_id: str = Query(...),
    antelope_account: str = Query(...)
):
    database = get_db()
    user = check_roles(database, antelope_account, ["screener", "resolver", "admin"])
    
    paper = database[GOLD_STANDARD_COLLECTION].find_one(
        {"project_id": project_id, "gs_id": gs_id},
        {"_id": 0}
    )
    if not paper:
        raise HTTPException(status_code=404, detail=f"Paper not found: {gs_id}")
    
    my_decision = database[DECISIONS_COLLECTION].find_one(
        {"project_id": project_id, "gs_id": gs_id, "antelope_account": antelope_account},
        {"_id": 0, "decision": 1, "confidence": 1, "reason": 1}
    )
    
    config = database[CONFIG_COLLECTION].find_one({"project_id": project_id}, {"_id": 0})
    
    return {
        **paper,
        "my_decision": my_decision,
        "screening_instructions": config.get("screening_instructions") if config else None,
        "user_roles": user.get("roles", [])
    }

@app.post("/api/papers/{gs_id}/decision")
async def submit_decision(
    gs_id: str,
    request: DecisionRequest,
    project_id: str = Query(...),
    antelope_account: str = Query(...)
):
    database = get_db()
    check_roles(database, antelope_account, ["screener", "resolver", "admin"])
    
    paper = database[GOLD_STANDARD_COLLECTION].find_one({"project_id": project_id, "gs_id": gs_id})
    if not paper:
        raise HTTPException(status_code=404, detail=f"Paper not found: {gs_id}")
    
    now = datetime.utcnow()
    decision_doc = {
        "project_id": project_id,
        "gs_id": gs_id,
        "antelope_account": antelope_account,
        "decision": request.decision.value,
        "confidence": request.confidence.value,
        "reason": request.reason,
        "updated_at": now
    }
    
    # NOTE: Unique index is on (gs_id, antelope_account) only
    database[DECISIONS_COLLECTION].update_one(
        {"gs_id": gs_id, "antelope_account": antelope_account},
        {"$set": decision_doc, "$setOnInsert": {"created_at": now}},
        upsert=True
    )
    
    bc_data = {
        "screener": antelope_account,
        "project_id": project_id,
        "gs_id": gs_id,
        "decision": request.decision.value,
        "confidence": request.confidence.value,
        "timestamp": now.isoformat()
    }
    tx_id = log_to_blockchain("logdecision", bc_data)
    
    if tx_id:
        database[DECISIONS_COLLECTION].update_one(
            {"gs_id": gs_id, "antelope_account": antelope_account},
            {"$set": {"blockchain_tx_id": tx_id}}
        )
    
    return {
        "success": True,
        "project_id": project_id,
        "gs_id": gs_id,
        "decision": request.decision.value,
        "blockchain_tx_id": tx_id
    }

@app.put("/api/papers/{gs_id}/fewshot")
async def toggle_paper_fewshot(
    gs_id: str,
    request: FewShotToggleRequest,
    project_id: str = Query(...),
    antelope_account: str = Query(...)
):
    """Toggle individual paper FEW-SHOT status (Admin only)."""
    database = get_db()
    check_roles(database, antelope_account, ["admin"])
    get_project(database, project_id)
    
    # Check if paper exists
    paper = database[GOLD_STANDARD_COLLECTION].find_one(
        {"project_id": project_id, "gs_id": gs_id}
    )
    
    if not paper:
        raise HTTPException(status_code=404, detail=f"Paper not found: {gs_id}")
    
    # If marking as calibration, check total count
    if request.is_calibration:
        current_count = database[GOLD_STANDARD_COLLECTION].count_documents(
            {"project_id": project_id, "is_calibration": True}
        )
        
        # If already at 10, don't allow adding more
        if current_count >= 10 and not paper.get("is_calibration", False):
            raise HTTPException(
                status_code=400,
                detail=f"Already have {current_count} FEW-SHOT papers. Remove one first or clear all."
            )
    
    # Update the paper
    database[GOLD_STANDARD_COLLECTION].update_one(
        {"project_id": project_id, "gs_id": gs_id},
        {"$set": {"is_calibration": request.is_calibration}}
    )
    
    return {
        "success": True,
        "gs_id": gs_id,
        "is_calibration": request.is_calibration,
        "message": f"Paper {'marked as' if request.is_calibration else 'removed from'} FEW-SHOT"
    }

@app.post("/api/fewshot/clear")
async def clear_fewshot_markers(
    project_id: str = Query(...),
    antelope_account: str = Query(...)
):
    """Clear all is_calibration flags from gold standard papers (Admin only)."""
    database = get_db()
    check_roles(database, antelope_account, ["admin"])
    get_project(database, project_id)
    
    # Clear all is_calibration flags
    result = database[GOLD_STANDARD_COLLECTION].update_many(
        {"project_id": project_id, "is_calibration": True},
        {"$set": {"is_calibration": False}}
    )
    
    return {
        "success": True,
        "project_id": project_id,
        "cleared_count": result.modified_count,
        "message": f"Cleared {result.modified_count} FEW-SHOT markers"
    }

@app.get("/api/disagreements")
async def list_disagreements(
    project_id: str = Query(...),
    antelope_account: str = Query(...)
):
    database = get_db()
    user = check_roles(database, antelope_account, ["resolver", "admin"])
    
    pipeline = [
        {"$match": {"project_id": project_id}},
        {"$group": {
            "_id": "$gs_id",
            "decisions": {"$push": {
                "user": "$antelope_account",
                "decision": "$decision",
                "confidence": "$confidence",
                "reason": "$reason"
            }},
            "count": {"$sum": 1}
        }},
        {"$match": {"count": {"$gte": 2}}}
    ]
    
    results = list(database[DECISIONS_COLLECTION].aggregate(pipeline))
    disagreements = []
    
    for item in results:
        decisions = item["decisions"]
        if len(decisions) >= 2:
            unique_decisions = set(d["decision"] for d in decisions)
            if len(unique_decisions) > 1:
                paper = database[GOLD_STANDARD_COLLECTION].find_one(
                    {"project_id": project_id, "gs_id": item["_id"], "is_calibration": {"$ne": True}},
                    {"_id": 0, "gs_id": 1, "title": 1, "abstract": 1}
                )
                
                resolution = database[RESOLUTIONS_COLLECTION].find_one(
                    {"project_id": project_id, "gs_id": item["_id"]},
                    {"_id": 0}
                )
                
                if paper:
                    disagreements.append({
                        **paper,
                        "decisions": decisions,
                        "resolved": resolution is not None,
                        "resolution": resolution
                    })
    
    return {
        "project_id": project_id,
        "disagreements": disagreements,
        "total": len(disagreements),
        "pending": len([d for d in disagreements if not d["resolved"]]),
        "user_roles": user.get("roles", [])
    }

@app.post("/api/papers/{gs_id}/resolve")
async def submit_resolution(
    gs_id: str,
    request: ResolutionRequest,
    project_id: str = Query(...),
    antelope_account: str = Query(...)
):
    database = get_db()
    check_roles(database, antelope_account, ["resolver", "admin"])
    
    decisions = list(database[DECISIONS_COLLECTION].find(
        {"project_id": project_id, "gs_id": gs_id},
        {"_id": 0}
    ))
    
    if len(decisions) < 2:
        raise HTTPException(status_code=400, detail="No disagreement to resolve")
    
    now = datetime.utcnow()
    resolution_doc = {
        "project_id": project_id,
        "gs_id": gs_id,
        "original_decisions": decisions,
        "final_decision": request.final_decision.value,
        "confidence": request.confidence.value,
        "resolution_reason": request.resolution_reason,
        "resolver": antelope_account,
        "resolved_at": now
    }
    
    database[RESOLUTIONS_COLLECTION].update_one(
        {"project_id": project_id, "gs_id": gs_id},
        {"$set": resolution_doc},
        upsert=True
    )
    
    bc_data = {
        "resolver": antelope_account,
        "project_id": project_id,
        "gs_id": gs_id,
        "final_decision": request.final_decision.value,
        "timestamp": now.isoformat()
    }
    tx_id = log_to_blockchain("logres", bc_data)
    
    if tx_id:
        database[RESOLUTIONS_COLLECTION].update_one(
            {"project_id": project_id, "gs_id": gs_id},
            {"$set": {"blockchain_tx_id": tx_id}}
        )
    
    return {
        "success": True,
        "project_id": project_id,
        "gs_id": gs_id,
        "final_decision": request.final_decision.value,
        "blockchain_tx_id": tx_id
    }

@app.get("/api/stats")
async def get_statistics(
    project_id: str = Query(...),
    antelope_account: str = Query(...)
):
    database = get_db()
    user = check_roles(database, antelope_account, ["admin"])
    project = get_project(database, project_id)
    
    corpus_count = database[CORPUS_COLLECTION].count_documents({"project_id": project_id})
    gs_count = database[GOLD_STANDARD_COLLECTION].count_documents({"project_id": project_id})
    
    user_stats_pipeline = [
        {"$match": {"project_id": project_id}},
        {"$group": {
            "_id": "$antelope_account",
            "total": {"$sum": 1},
            "include": {"$sum": {"$cond": [{"$eq": ["$decision", "INCLUDE"]}, 1, 0]}},
            "exclude": {"$sum": {"$cond": [{"$eq": ["$decision", "EXCLUDE"]}, 1, 0]}},
            "uncertain": {"$sum": {"$cond": [{"$eq": ["$decision", "UNCERTAIN"]}, 1, 0]}}
        }}
    ]
    
    screener_stats = {item["_id"]: item for item in database[DECISIONS_COLLECTION].aggregate(user_stats_pipeline)}
    kappa_stats = calculate_cohens_kappa(database, project_id)
    resolutions_count = database[RESOLUTIONS_COLLECTION].count_documents({"project_id": project_id})
    
    final_stats_pipeline = [
        {"$match": {"project_id": project_id}},
        {"$group": {"_id": "$final_decision", "count": {"$sum": 1}}}
    ]
    final_distribution = {item["_id"]: item["count"] for item in database[RESOLUTIONS_COLLECTION].aggregate(final_stats_pipeline)}
    
    # FEW-SHOT statistics
    fewshot_papers = list(database[GOLD_STANDARD_COLLECTION].find(
        {"project_id": project_id, "is_calibration": True},
        {"_id": 0, "gs_id": 1}
    ))
    fewshot_gs_ids = [p["gs_id"] for p in fewshot_papers]
    
    fewshot_stats = {"total": 0, "include": 0, "exclude": 0, "uncertain": 0}
    if fewshot_gs_ids:
        fewshot_pipeline = [
            {"$match": {"project_id": project_id, "gs_id": {"$in": fewshot_gs_ids}}},
            {"$group": {
                "_id": "$decision",
                "count": {"$sum": 1}
            }}
        ]
        fewshot_decisions = list(database[DECISIONS_COLLECTION].aggregate(fewshot_pipeline))
        
        for item in fewshot_decisions:
            decision = item["_id"]
            count = item["count"]
            if decision == "INCLUDE":
                fewshot_stats["include"] = count
            elif decision == "EXCLUDE":
                fewshot_stats["exclude"] = count
            elif decision == "UNCERTAIN":
                fewshot_stats["uncertain"] = count
        
        fewshot_stats["total"] = len(fewshot_gs_ids)
    
    return {
        "project_id": project_id,
        "project_name": project.get("name", ""),
        "corpus_count": corpus_count,
        "gold_standard_count": gs_count,
        "screeners": screener_stats,
        "agreement": kappa_stats,
        "resolutions": {
            "total": resolutions_count,
            "by_decision": final_distribution
        },
        "fewshot": fewshot_stats,
        "user_roles": user.get("roles", [])
    }

@app.get("/api/export")
async def export_results(
    project_id: str = Query(...),
    antelope_account: str = Query(...)
):
    database = get_db()
    user = check_roles(database, antelope_account, ["admin"])
    project = get_project(database, project_id)
    
    papers = list(database[GOLD_STANDARD_COLLECTION].find({"project_id": project_id}, {"_id": 0}).sort("gs_id", 1))
    
    decisions = list(database[DECISIONS_COLLECTION].find({"project_id": project_id}, {"_id": 0}))
    decisions_by_paper = {}
    for d in decisions:
        gs_id = d["gs_id"]
        if gs_id not in decisions_by_paper:
            decisions_by_paper[gs_id] = []
        decisions_by_paper[gs_id].append(d)
    
    resolutions = {r["gs_id"]: r for r in database[RESOLUTIONS_COLLECTION].find({"project_id": project_id}, {"_id": 0})}
    
    export_papers = []
    for paper in papers:
        gs_id = paper["gs_id"]
        paper_decisions = decisions_by_paper.get(gs_id, [])
        resolution = resolutions.get(gs_id)
        
        screener1 = paper_decisions[0] if len(paper_decisions) > 0 else None
        screener2 = paper_decisions[1] if len(paper_decisions) > 1 else None
        
        agreement = screener1["decision"] == screener2["decision"] if screener1 and screener2 else None
        
        if resolution:
            final_decision = resolution["final_decision"]
        elif agreement:
            final_decision = screener1["decision"] if screener1 else None
        else:
            final_decision = None
        
        export_papers.append({
            **paper,
            "screener1_account": screener1["antelope_account"] if screener1 else None,
            "screener1_decision": screener1["decision"] if screener1 else None,
            "screener1_confidence": screener1.get("confidence") if screener1 else None,
            "screener1_reason": screener1.get("reason") if screener1 else None,
            "screener2_account": screener2["antelope_account"] if screener2 else None,
            "screener2_decision": screener2["decision"] if screener2 else None,
            "screener2_confidence": screener2.get("confidence") if screener2 else None,
            "screener2_reason": screener2.get("reason") if screener2 else None,
            "agreement": agreement,
            "final_decision": final_decision,
            "resolution_reason": resolution.get("resolution_reason") if resolution else None,
            "resolver": resolution.get("resolver") if resolution else None
        })
    
    kappa_stats = calculate_cohens_kappa(database, project_id)
    
    return {
        "metadata": {
            "project_id": project_id,
            "project_name": project.get("name", ""),
            "corpus_count": project.get("corpus_count", 0),
            "exported_at": datetime.utcnow().isoformat(),
            "exported_by": antelope_account,
            "statistics": {
                "gold_standard_count": len(papers),
                "with_decisions": len([p for p in export_papers if p["screener1_decision"]]),
                "agreements": kappa_stats.get("agreements", 0),
                "disagreements": kappa_stats.get("n", 0) - kappa_stats.get("agreements", 0),
                "cohens_kappa": kappa_stats.get("cohens_kappa"),
                "interpretation": kappa_stats.get("interpretation"),
                "final_include": len([p for p in export_papers if p["final_decision"] == "INCLUDE"]),
                "final_exclude": len([p for p in export_papers if p["final_decision"] == "EXCLUDE"]),
                "final_uncertain": len([p for p in export_papers if p["final_decision"] == "UNCERTAIN"])
            }
        },
        "papers": export_papers
    }

# =============================================================================
# BLOCKCHAIN AUDIT ENDPOINTS
# =============================================================================

@app.get("/api/audit/status")
async def get_audit_status(
    project_id: str = Query(...),
    antelope_account: str = Query(...)
):
    """Get audit status for a project."""
    database = get_db()
    check_roles(database, antelope_account, ["admin"])
    get_project(database, project_id)
    
    # Get decision stats
    total_decisions = database[DECISIONS_COLLECTION].count_documents({"project_id": project_id})
    blockchain_logged = database[DECISIONS_COLLECTION].count_documents({
        "project_id": project_id,
        "blockchain_tx_id": {"$exists": True, "$ne": None}
    })
    
    # Get audit exports
    exports = list(database[AUDIT_EXPORTS_COLLECTION].find(
        {"project_id": project_id},
        {"_id": 0}
    ).sort("created_at", -1))
    
    print(f"📊 Checking {len(exports)} exports for project {project_id}")
    
    # Check pending timestamps before returning
    for export in exports:
        if export.get("ots_status") == "pending" and export.get("ots_proof"):
            print(f"🔍 Verifying pending timestamp: {export['export_id']} ({export.get('filename')})")
            try:
                # Create temporary file with the hash (original file)
                with tempfile.NamedTemporaryFile(mode='w', suffix='.hash', delete=False) as f:
                    f.write(export["file_hash"])
                    hash_path = f.name
                
                # Create the .ots file
                ots_path = f"{hash_path}.ots"
                with open(ots_path, 'wb') as f:
                    f.write(base64.b64decode(export["ots_proof"]))
                
                print(f"  → Created hash file: {hash_path}")
                print(f"  → Created OTS file: {ots_path}")
                
                # Check if confirmed
                result = verify_opentimestamps(ots_path)
                print(f"  → Verification result: {result}")
                
                # Cleanup
                os.unlink(hash_path)
                os.unlink(ots_path)
                
                if result["status"] == "confirmed":
                    # Update database
                    database[AUDIT_EXPORTS_COLLECTION].update_one(
                        {"export_id": export["export_id"]},
                        {"$set": {
                            "ots_status": "confirmed",
                            "ots_confirmed_at": datetime.utcnow(),
                            "ots_verification_message": result["message"]
                        }}
                    )
                    # Update in-memory export object
                    export["ots_status"] = "confirmed"
                    print(f"✓ Timestamp confirmed for {export['export_id']}")
                else:
                    print(f"  → Still pending: {result.get('message', 'Unknown')}")
                    
            except Exception as e:
                print(f"⚠️ Error checking timestamp for {export.get('export_id')}: {e}")
                import traceback
                traceback.print_exc()
    
    # Add labels for milestones
    milestone_labels = {
        'protocol_registered': 'Protocol Registered',
        'gold_standard_complete': 'Gold Standard Complete',
        'llm_screening_complete': 'LLM Screening Complete',
        'final_corpus': 'Final Corpus',
        'quick_export': 'Quick Export'
    }
    
    for export in exports:
        export["milestone_label"] = milestone_labels.get(export.get("milestone"), export.get("milestone"))
    
    return {
        "project_id": project_id,
        "stats": {
            "total_decisions": total_decisions,
            "blockchain_logged": blockchain_logged,
            "coverage_percent": round(blockchain_logged / total_decisions * 100, 1) if total_decisions > 0 else 0
        },
        "exports": exports
    }

@app.post("/api/audit/export")
async def create_audit_export(
    request: AuditExportRequest,
    project_id: str = Query(...),
    antelope_account: str = Query(...)
):
    """Create an audit export with Merkle root calculation.

    v5.0.0: Extended to include GS and FC LLM decisions, job metadata,
    and final inclusion list for Zenodo publication.

    Export structure:
      A. human_decisions   – expert screening decisions (screening_decisions collection)
      B. resolutions       – disagreement resolutions (resolutions collection)
      C. llm_gs_decisions  – GS LLM evaluation, all configs (data_source=gold_standard)
      D. llm_fc_decisions  – FC LLM screening, 5 configs (data_source=corpus)
      E. llm_jobs          – job metadata for all LLM jobs
      F. final_inclusion_list – papers selected for full-text review
    """
    try:
        database = get_db()
        check_roles(database, antelope_account, ["admin"])
        project = get_project(database, project_id)

        now = datetime.utcnow()
        milestone = request.milestone or "quick_export"

        # ── A. Gather human decisions ────────────────────────────
        decisions = list(database[DECISIONS_COLLECTION].find(
            {"project_id": project_id},
            {"_id": 0}
        ).sort([("gs_id", 1), ("antelope_account", 1)]))

        # ── B. Gather resolutions ────────────────────────────────
        resolutions = list(database[RESOLUTIONS_COLLECTION].find(
            {"project_id": project_id},
            {"_id": 0}
        ).sort("gs_id", 1))

        # ── C+D. Gather LLM decisions (compact) ─────────────────
        llm_gs_decisions = {}
        llm_fc_decisions = {}
        llm_jobs_list = []

        if request.include_llm_decisions:
            has_llm_decs = LLM_DECISIONS_COLLECTION in database.list_collection_names()
            has_llm_jobs = LLM_JOBS_COLLECTION in database.list_collection_names()

            if has_llm_jobs:
                llm_jobs_list = list(database[LLM_JOBS_COLLECTION].find(
                    {"project_id": project_id},
                    {"_id": 0}
                ).sort("created_at", 1))

            if has_llm_decs:
                compact_projection = {
                    "_id": 0,
                    "agent_responses": 0,
                    "reasoning": 0,
                    "aggregation": 0,
                    "raw_output": 0,
                }

                all_llm_decisions = list(database[LLM_DECISIONS_COLLECTION].find(
                    {"project_id": project_id},
                    compact_projection
                ).sort([("job_id", 1), ("gs_id", 1)]))

                job_source_map = {}
                for j in llm_jobs_list:
                    jid = j.get("job_id", "")
                    ds = j.get("data_source", "unknown")
                    job_source_map[jid] = ds

                for dec in all_llm_decisions:
                    jid = dec.get("job_id", "unknown")
                    data_source = dec.get("data_source") or job_source_map.get(jid, "unknown")

                    if data_source == "corpus":
                        if jid not in llm_fc_decisions:
                            llm_fc_decisions[jid] = []
                        llm_fc_decisions[jid].append(dec)
                    else:
                        if jid not in llm_gs_decisions:
                            llm_gs_decisions[jid] = []
                        llm_gs_decisions[jid].append(dec)

        # ── E. Build final inclusion list ────────────────────────
        final_inclusion_list = None

        if request.inclusion_list_job_id:
            has_llm_decs = LLM_DECISIONS_COLLECTION in database.list_collection_names()
            if has_llm_decs:
                included_papers = list(database[LLM_DECISIONS_COLLECTION].find(
                    {
                        "project_id": project_id,
                        "job_id": request.inclusion_list_job_id,
                        "final_decision": "INCLUDE"
                    },
                    {
                        "_id": 0,
                        "gs_id": 1,
                        "paper_id": 1,
                        "title": 1,
                        "final_decision": 1,
                        "final_confidence": 1,
                        "confidence_score": 1,
                        "model": 1,
                        "strategy": 1,
                        "prompt_mode": 1,
                        "transaction_id": 1,
                    }
                ).sort("gs_id", 1))

                job_meta = None
                for j in llm_jobs_list:
                    if j.get("job_id") == request.inclusion_list_job_id:
                        job_meta = j
                        break

                final_inclusion_list = {
                    "description": "Papers selected for full-text screening based on the best-performing configuration",
                    "source_job_id": request.inclusion_list_job_id,
                    "source_config": (
                        f"{(job_meta.get('strategies') or ['N/A'])[0]} / "
                        f"{job_meta.get('models', job_meta.get('model', 'N/A'))} / "
                        f"{job_meta.get('prompt_mode', 'N/A')}"
                    ) if job_meta else "N/A",
                    "total_included": len(included_papers),
                    "papers": included_papers
                }

        # ── F. Build export data ─────────────────────────────────
        total_gs_llm = sum(len(v) for v in llm_gs_decisions.values())
        total_fc_llm = sum(len(v) for v in llm_fc_decisions.values())

        export_data = {
            "metadata": {
                "project_id": project_id,
                "project_name": project.get("name", ""),
                "milestone": milestone,
                "exported_at": now.isoformat(),
                "exported_by": antelope_account,
                "version": "5.0.0",
                "description": (
                    "Complete audit log of title-abstract screening decisions. "
                    "Contains human expert decisions (Section A), disagreement resolutions (Section B), "
                    "LLM evaluation decisions on Gold Standard (Section C), "
                    "LLM screening decisions on Full Corpus (Section D), "
                    "LLM job metadata (Section E), and final inclusion list for full-text review (Section F)."
                )
            },
            "human_decisions": decisions,
            "resolutions": resolutions,
            "statistics": {
                "total_human_decisions": len(decisions),
                "total_resolutions": len(resolutions),
                "total_gs_llm_decisions": total_gs_llm,
                "total_gs_llm_configs": len(llm_gs_decisions),
                "total_fc_llm_decisions": total_fc_llm,
                "total_fc_llm_configs": len(llm_fc_decisions),
                "total_llm_jobs": len(llm_jobs_list),
            }
        }

        if llm_gs_decisions:
            export_data["llm_gs_decisions"] = llm_gs_decisions

        if llm_fc_decisions:
            export_data["llm_fc_decisions"] = llm_fc_decisions

        if llm_jobs_list:
            export_data["llm_jobs"] = llm_jobs_list

        if final_inclusion_list:
            export_data["final_inclusion_list"] = final_inclusion_list
            export_data["statistics"]["total_included_for_fulltext"] = final_inclusion_list["total_included"]

        # ── G. Build Merkle tree ─────────────────────────────────
        all_records = decisions + resolutions
        for job_decs in llm_gs_decisions.values():
            all_records.extend(job_decs)
        for job_decs in llm_fc_decisions.values():
            all_records.extend(job_decs)

        merkle_data = build_merkle_tree(all_records)

        # ── H. Generate export ID and filename ───────────────────
        export_id = generate_export_id()
        timestamp_str = now.strftime("%Y%m%d_%H%M%S")
        filename = f"{project_id}_{milestone}_{timestamp_str}.json"

        # ── I. Log to blockchain via logaudit action ─────────────
        # We log merkle_root to blockchain first (it doesn't depend on file_hash).
        # file_hash is computed after, once the audit section (incl. tx_id) is embedded.
        # For the blockchain filehash field, we use the merkle_root as a placeholder
        # since the real file_hash has a circular dependency on tx_id.
        bc_data = {
            "admin": antelope_account,
            "project_id": project_id,
            "milestone": milestone,
            "merkle_root": merkle_data["root"],
            "file_hash": merkle_data["root"],
            "leaf_count": merkle_data["count"]
        }

        try:
            tx_id = log_to_blockchain("logaudit", bc_data)
        except Exception as bc_error:
            print(f"[AUDIT_EXPORT] Blockchain logging failed: {bc_error}")
            tx_id = f"ERROR_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"

        # ── J. Add audit section BEFORE hashing ──────────────────
        # The audit section is part of the downloaded file, so it must be
        # included when computing the hash. file_hash is excluded from the
        # hash computation (circular dependency) and stored separately.
        export_data["audit"] = {
            "merkle_root": merkle_data["root"],
            "merkle_leaf_count": merkle_data["count"],
            "blockchain_tx_id": tx_id
        }

        # ── K. Compute file hash (audit section included, file_hash excluded)
        export_json = json.dumps(export_data, sort_keys=True, default=str)
        file_hash = compute_sha256(export_json)

        # Now add file_hash for display (not part of the verified hash)
        export_data["audit"]["file_hash"] = file_hash

        # ── L. Store export record ───────────────────────────────
        export_record = {
            "export_id": export_id,
            "project_id": project_id,
            "milestone": milestone,
            "filename": filename,
            "file_hash": file_hash,
            "file_size": len(export_json),
            "merkle_root": merkle_data["root"],
            "merkle_leaf_count": merkle_data["count"],
            "blockchain_tx_id": tx_id,
            "ots_status": "not_timestamped",
            "ots_proof": None,
            "created_at": now,
            "created_by": antelope_account
        }

        database[AUDIT_EXPORTS_COLLECTION].insert_one(export_record)

        print(f"[AUDIT_EXPORT] Export created: {export_id}")
        print(f"  Human decisions: {len(decisions)}")
        print(f"  Resolutions: {len(resolutions)}")
        print(f"  GS LLM configs: {len(llm_gs_decisions)}, decisions: {total_gs_llm}")
        print(f"  FC LLM configs: {len(llm_fc_decisions)}, decisions: {total_fc_llm}")
        print(f"  Inclusion list: {final_inclusion_list['total_included'] if final_inclusion_list else 0}")
        print(f"  Merkle leaves: {merkle_data['count']}")
        print(f"  File size: {len(export_json):,} bytes")

        return {
            "success": True,
            "export_id": export_id,
            "filename": filename,
            "merkle_root": merkle_data["root"],
            "file_hash": file_hash,
            "blockchain_tx_id": tx_id,
            "export_data": export_data
        }
    except Exception as e:
        import traceback
        print(f"[AUDIT_EXPORT] Error: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Audit export failed: {str(e)}")

@app.post("/api/audit/timestamp")
async def submit_timestamp(
    request: TimestampRequest,
    project_id: str = Query(...),
    antelope_account: str = Query(...)
):
    """Submit an export file to OpenTimestamps."""
    database = get_db()
    check_roles(database, antelope_account, ["admin"])
    
    # Find the export
    export_record = database[AUDIT_EXPORTS_COLLECTION].find_one({
        "project_id": project_id,
        "export_id": request.export_id
    })
    
    if not export_record:
        raise HTTPException(status_code=404, detail=f"Export not found: {request.export_id}")
    
    if export_record.get("ots_status") != "not_timestamped":
        raise HTTPException(status_code=400, detail="Export already timestamped or pending")
    
    # Create temporary file with the hash
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.hash', delete=False) as f:
            f.write(export_record["file_hash"])
            temp_path = f.name
        
        # Submit to OpenTimestamps
        ots_file = submit_to_opentimestamps(temp_path)
        
        if ots_file and os.path.exists(ots_file):
            # Read the OTS proof
            with open(ots_file, 'rb') as f:
                ots_proof = base64.b64encode(f.read()).decode('utf-8')
            
            # Update record
            database[AUDIT_EXPORTS_COLLECTION].update_one(
                {"export_id": request.export_id},
                {"$set": {
                    "ots_status": "pending",
                    "ots_proof": ots_proof,
                    "ots_submitted_at": datetime.utcnow()
                }}
            )
            
            # Cleanup
            os.unlink(temp_path)
            os.unlink(ots_file)
            
            return {
                "success": True,
                "export_id": request.export_id,
                "status": "pending",
                "message": "Submitted to OpenTimestamps. Confirmation will take ~2-4 hours."
            }
        else:
            os.unlink(temp_path)
            raise HTTPException(status_code=500, detail="Failed to create timestamp")
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Timestamp error: {str(e)}")

@app.get("/api/audit/proof/{export_id}")
async def get_proof(
    export_id: str,
    project_id: str = Query(...),
    antelope_account: str = Query(...)
):
    """Download OTS proof file."""
    database = get_db()
    check_roles(database, antelope_account, ["admin"])
    
    export_record = database[AUDIT_EXPORTS_COLLECTION].find_one({
        "project_id": project_id,
        "export_id": export_id
    })
    
    if not export_record:
        raise HTTPException(status_code=404, detail=f"Export not found: {export_id}")
    
    if not export_record.get("ots_proof"):
        raise HTTPException(status_code=404, detail="No OTS proof available")
    
    return {
        "export_id": export_id,
        "filename": f"{export_record['filename']}.ots",
        "ots_proof_base64": export_record["ots_proof"],
        "ots_status": export_record.get("ots_status", "unknown")
    }

@app.post("/api/audit/verify")
async def verify_file(
    request: VerifyRequest,
    project_id: str = Query(...),
    antelope_account: str = Query(...)
):
    """Verify a file against stored audit records."""
    database = get_db()
    check_roles(database, antelope_account, ["admin"])

    # Compute hash of provided content
    file_hash = compute_sha256(request.file_content)

    # Also try hash without audit.file_hash (v5.0.0 exports include it
    # as a convenience field added AFTER the canonical hash was computed)
    file_hash_stripped = None
    try:
        parsed = json.loads(request.file_content)
        if isinstance(parsed.get("audit"), dict) and "file_hash" in parsed["audit"]:
            del parsed["audit"]["file_hash"]
            stripped_json = json.dumps(parsed, sort_keys=True, default=str)
            file_hash_stripped = compute_sha256(stripped_json)
    except (json.JSONDecodeError, TypeError):
        pass

    # Search for matching export (try both hashes)
    matching_export = database[AUDIT_EXPORTS_COLLECTION].find_one({
        "project_id": project_id,
        "file_hash": {"$in": [h for h in [file_hash, file_hash_stripped] if h]}
    }, {"_id": 0})
    
    if matching_export:
        return {
            "valid": True,
            "message": f"File matches audit export from {matching_export.get('created_at')}",
            "matched_export": {
                "export_id": matching_export["export_id"],
                "filename": matching_export["filename"],
                "merkle_root": matching_export["merkle_root"],
                "blockchain_tx_id": matching_export.get("blockchain_tx_id"),
                "created_at": matching_export["created_at"].isoformat() if matching_export.get("created_at") else None
            },
            "computed_hash": file_hash
        }
    else:
        return {
            "valid": False,
            "message": "No matching audit export found for this file",
            "computed_hash": file_hash
        }

@app.post("/api/audit/check-timestamps")
async def check_timestamps(
    project_id: str = Query(...),
    antelope_account: str = Query(...)
):
    """Check status of pending timestamps (background task)."""
    database = get_db()
    check_roles(database, antelope_account, ["admin"])
    
    pending_exports = list(database[AUDIT_EXPORTS_COLLECTION].find({
        "project_id": project_id,
        "ots_status": "pending"
    }))
    
    updated = []
    
    for export in pending_exports:
        if export.get("ots_proof"):
            # Write proof to temp file and verify
            try:
                with tempfile.NamedTemporaryFile(mode='wb', suffix='.ots', delete=False) as f:
                    f.write(base64.b64decode(export["ots_proof"]))
                    ots_path = f.name
                
                result = verify_opentimestamps(ots_path)
                os.unlink(ots_path)
                
                if result["status"] == "confirmed":
                    database[AUDIT_EXPORTS_COLLECTION].update_one(
                        {"export_id": export["export_id"]},
                        {"$set": {
                            "ots_status": "confirmed",
                            "ots_confirmed_at": datetime.utcnow(),
                            "ots_verification_message": result["message"]
                        }}
                    )
                    updated.append({
                        "export_id": export["export_id"],
                        "new_status": "confirmed"
                    })
                    
            except Exception as e:
                print(f"Error checking timestamp for {export['export_id']}: {e}")
    
    return {
        "checked": len(pending_exports),
        "updated": updated
    }

# =============================================================================
# ADMIN MANAGEMENT ENDPOINTS
# =============================================================================

@app.get("/api/admin/projects/all")
async def get_all_projects_admin(
    antelope_account: str = Query(...)
):
    """Get all projects with detailed execution status (admin only)."""
    database = get_db()
    check_roles(database, antelope_account, ["admin"])
    
    projects = list(database[PROJECTS_COLLECTION].find({}, {"_id": 0}))
    
    for project in projects:
        pid = project["project_id"]
        
        # Count corpus
        corpus_count = database[CORPUS_COLLECTION].count_documents({"project_id": pid})
        
        # Count gold standard (total, calibration, evaluation)
        gs_total = database[GOLD_STANDARD_COLLECTION].count_documents({"project_id": pid})
        gs_calibration = database[GOLD_STANDARD_COLLECTION].count_documents({
            "project_id": pid, 
            "is_calibration": True
        })
        gs_evaluation = gs_total - gs_calibration
        
        # Count human screening decisions
        human_decisions = database[DECISIONS_COLLECTION].count_documents({"project_id": pid})
        human_screened_papers = len(database[DECISIONS_COLLECTION].distinct("gs_id", {"project_id": pid}))
        
        # Count LLM decisions
        llm_decisions = database["llm_decisions"].count_documents({"project_id": pid}) if "llm_decisions" in database.list_collection_names() else 0
        llm_strategies = list(database["llm_decisions"].distinct("strategy", {"project_id": pid})) if "llm_decisions" in database.list_collection_names() else []
        
        # Count evaluations
        evaluations = database["evaluation_results"].count_documents({"project_id": pid}) if "evaluation_results" in database.list_collection_names() else 0
        
        # Count audit exports
        audit_exports = database[AUDIT_EXPORTS_COLLECTION].count_documents({"project_id": pid})
        
        # Determine execution phase
        phase = "1_data_loaded"
        if human_decisions > 0:
            phase = "2_human_screening"
        if llm_decisions > 0:
            phase = "3_llm_screening"
        if evaluations > 0:
            phase = "4_evaluation_complete"
        
        project["execution_status"] = {
            "phase": phase,
            "corpus_count": corpus_count,
            "gold_standard": {
                "total": gs_total,
                "calibration": gs_calibration,
                "evaluation": gs_evaluation
            },
            "human_screening": {
                "decisions_count": human_decisions,
                "papers_screened": human_screened_papers,
                "progress": round((human_screened_papers / gs_total * 100), 1) if gs_total > 0 else 0
            },
            "llm_screening": {
                "decisions_count": llm_decisions,
                "strategies_used": llm_strategies
            },
            "evaluation": {
                "results_count": evaluations
            },
            "audit": {
                "exports_count": audit_exports
            }
        }
    
    return {"projects": projects}

@app.post("/api/admin/projects/{project_id}/clear")
async def clear_project_results(
    project_id: str,
    antelope_account: str = Query(...),
    clear_type: str = Query("all", regex="^(all|human|llm|evaluation|audit|fewshot)$")
):
    """
    Clear project results while keeping base data.
    
    Args:
        clear_type: 'all', 'human', 'llm', 'evaluation', 'audit', or 'fewshot'
    """
    database = get_db()
    check_roles(database, antelope_account, ["admin"])
    
    # Verify project exists
    project = database[PROJECTS_COLLECTION].find_one({"project_id": project_id})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    results = {
        "project_id": project_id,
        "cleared": [],
        "counts": {}
    }
    
    if clear_type in ["all", "human"]:
        # Clear human screening decisions
        decisions_deleted = database[DECISIONS_COLLECTION].delete_many({"project_id": project_id})
        results["counts"]["human_decisions"] = decisions_deleted.deleted_count
        results["cleared"].append("human_decisions")
        
        # Clear resolutions
        resolutions_deleted = database[RESOLUTIONS_COLLECTION].delete_many({"project_id": project_id})
        results["counts"]["resolutions"] = resolutions_deleted.deleted_count
        results["cleared"].append("resolutions")
    
    if clear_type in ["all", "llm"]:
        # Clear LLM decisions
        if "llm_decisions" in database.list_collection_names():
            llm_deleted = database["llm_decisions"].delete_many({"project_id": project_id})
            results["counts"]["llm_decisions"] = llm_deleted.deleted_count
            results["cleared"].append("llm_decisions")
        
        # Clear LLM screening jobs
        if "llm_jobs" in database.list_collection_names():
            jobs_deleted = database["llm_jobs"].delete_many({"project_id": project_id})
            results["counts"]["llm_jobs"] = jobs_deleted.deleted_count
            results["cleared"].append("llm_jobs")
    
    if clear_type in ["all", "evaluation"]:
        # Clear evaluation results
        if "evaluation_results" in database.list_collection_names():
            eval_deleted = database["evaluation_results"].delete_many({"project_id": project_id})
            results["counts"]["evaluation_results"] = eval_deleted.deleted_count
            results["cleared"].append("evaluation_results")
    
    if clear_type in ["all", "audit"]:
        # Clear audit exports (but keep blockchain transactions)
        audit_deleted = database[AUDIT_EXPORTS_COLLECTION].delete_many({"project_id": project_id})
        results["counts"]["audit_exports"] = audit_deleted.deleted_count
        results["cleared"].append("audit_exports")
    
    if clear_type == "fewshot":
        # Clear FEW-SHOT markers (set is_calibration to False)
        fewshot_result = database[GOLD_STANDARD_COLLECTION].update_many(
            {"project_id": project_id, "is_calibration": True},
            {"$set": {"is_calibration": False}}
        )
        results["counts"]["fewshot_cleared"] = fewshot_result.modified_count
        results["cleared"].append("fewshot_markers")
    
    # Log to blockchain
    log_to_blockchain("clear_project", {
        "project_id": project_id,
        "clear_type": clear_type,
        "user": antelope_account,
        "results": results
    })
    
    return results

@app.get("/api/admin/projects/{project_id}/actions")
async def get_project_actions(
    project_id: str,
    antelope_account: str = Query(...),
    limit: int = Query(100, ge=10, le=1000)
):
    """Get all actions/history for a project (admin only)."""
    database = get_db()
    check_roles(database, antelope_account, ["admin"])
    
    # Collect all actions from different collections
    actions = []
    
    # Human screening decisions
    decisions = list(database[DECISIONS_COLLECTION].find(
        {"project_id": project_id},
        {"_id": 0, "blockchain_tx_id": 1, "blockchain_tx": 1, "antelope_account": 1, "gs_id": 1, "decision": 1, "confidence": 1, "updated_at": 1, "created_at": 1, "submitted_at": 1}
    ).sort("updated_at", -1).limit(limit))
    
    for d in decisions:
        timestamp = d.get("updated_at") or d.get("created_at") or d.get("submitted_at")
        actions.append({
            "type": "human_decision",
            "timestamp": timestamp.isoformat() if hasattr(timestamp, 'isoformat') else timestamp,
            "user": d.get("antelope_account"),
            "gs_id": d.get("gs_id"),
            "decision": d.get("decision"),
            "confidence": d.get("confidence"),
            "transaction_id": d.get("blockchain_tx_id") or d.get("blockchain_tx")
        })
    
    # Resolutions
    resolutions = list(database[RESOLUTIONS_COLLECTION].find(
        {"project_id": project_id},
        {"_id": 0, "blockchain_tx_id": 1, "blockchain_tx": 1, "resolver": 1, "gs_id": 1, "final_decision": 1, "resolved_at": 1}
    ).sort("resolved_at", -1).limit(limit))
    
    for r in resolutions:
        timestamp = r.get("resolved_at")
        actions.append({
            "type": "resolution",
            "timestamp": timestamp.isoformat() if hasattr(timestamp, 'isoformat') else timestamp,
            "user": r.get("resolver"),
            "gs_id": r.get("gs_id"),
            "decision": r.get("final_decision"),
            "transaction_id": r.get("blockchain_tx_id") or r.get("blockchain_tx")
        })
    
    # LLM decisions (sample)
    if "llm_decisions" in database.list_collection_names():
        llm_decisions = list(database["llm_decisions"].find(
            {"project_id": project_id},
            {"_id": 0, "project_id": 1, "strategy": 1, "model": 1, "created_at": 1, "transaction_id": 1, 
             "gs_id": 1, "paper_id": 1, "final_decision": 1, "antelope_account": 1}
        ).sort("created_at", -1).limit(50))
        
        for ld in llm_decisions:
            timestamp = ld.get("created_at")
            actions.append({
                "type": "llm_decision",
                "timestamp": timestamp.isoformat() if hasattr(timestamp, 'isoformat') else timestamp,
                "strategy": ld.get("strategy"),
                "model": ld.get("model"),
                "user": ld.get("antelope_account"),
                "gs_id": ld.get("gs_id") or ld.get("paper_id"),
                "decision": ld.get("final_decision"),
                "transaction_id": ld.get("transaction_id")
            })
    
    # Audit exports
    audit_exports = list(database[AUDIT_EXPORTS_COLLECTION].find(
        {"project_id": project_id},
        {"_id": 0}
    ).sort("created_at", -1))
    
    for ae in audit_exports:
        timestamp = ae.get("created_at")
        actions.append({
            "type": "audit_export",
            "timestamp": timestamp.isoformat() if hasattr(timestamp, 'isoformat') else timestamp,
            "export_id": ae.get("export_id"),
            "milestone": ae.get("milestone"),
            "ots_status": ae.get("ots_status")
        })
    
    # Sort all actions by timestamp (handle None/empty values)
    actions.sort(key=lambda x: x.get("timestamp") or "", reverse=True)
    
    return {
        "project_id": project_id,
        "total_actions": len(actions),
        "actions": actions[:limit]
    }

@app.get("/api/users/{antelope_account}/actions")
async def get_user_actions(
    antelope_account: str,
    requesting_user: str = Query(..., alias="antelope_account"),
    project_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=10, le=1000)
):
    """Get user's action log (users can view their own, admins can view any)."""
    database = get_db()
    
    # Check authorization: user can view own actions, admin can view any
    requesting_user_info = get_user_info(database, requesting_user)
    if not requesting_user_info:
        raise HTTPException(status_code=401, detail="User not found")
    
    is_admin = "admin" in requesting_user_info.get("roles", [])
    if antelope_account != requesting_user and not is_admin:
        raise HTTPException(status_code=403, detail="Can only view your own actions")
    
    actions = []
    query = {"antelope_account": antelope_account}
    if project_id:
        query["project_id"] = project_id
    
    # Get screening decisions
    decisions = list(database[DECISIONS_COLLECTION].find(
        query,
        {"_id": 0}
    ).sort("updated_at", -1).limit(limit))
    
    for d in decisions:
        # Use updated_at, or fall back to created_at, or submitted_at for compatibility
        timestamp = d.get("updated_at") or d.get("created_at") or d.get("submitted_at")
        actions.append({
            "type": "screening_decision",
            "timestamp": timestamp.isoformat() if hasattr(timestamp, 'isoformat') else timestamp,
            "project_id": d.get("project_id"),
            "gs_id": d.get("gs_id"),
            "decision": d.get("decision"),
            "confidence": d.get("confidence"),
            "blockchain_tx": d.get("blockchain_tx_id") or d.get("blockchain_tx")
        })
    
    # Get resolutions (if user is resolver)
    resolutions = list(database[RESOLUTIONS_COLLECTION].find(
        {"resolver": antelope_account, **({"project_id": project_id} if project_id else {})},
        {"_id": 0}
    ).sort("resolved_at", -1).limit(limit))
    
    for r in resolutions:
        timestamp = r.get("resolved_at")
        actions.append({
            "type": "resolution",
            "timestamp": timestamp.isoformat() if hasattr(timestamp, 'isoformat') else timestamp,
            "project_id": r.get("project_id"),
            "gs_id": r.get("gs_id"),
            "decision": r.get("final_decision"),
            "blockchain_tx": r.get("blockchain_tx_id") or r.get("blockchain_tx")
        })
    
    # Get LLM screening decisions (Phase 6+)
    llm_decisions = list(database["llm_decisions"].find(
        {"antelope_account": antelope_account, **({"project_id": project_id} if project_id else {})},
        {"_id": 0}
    ).sort("timestamp", -1).limit(limit))
    
    for ld in llm_decisions:
        timestamp = ld.get("timestamp")
        actions.append({
            "type": "llm_screening",
            "timestamp": timestamp.isoformat() if hasattr(timestamp, 'isoformat') else timestamp,
            "project_id": ld.get("project_id"),
            "gs_id": ld.get("gs_id"),
            "decision": ld.get("final_decision"),
            "confidence": ld.get("final_confidence"),
            "strategy": ld.get("strategy"),
            "model": ld.get("model"),
            "job_id": ld.get("job_id"),
            "blockchain_tx": ld.get("transaction_id")  # NEW: Include blockchain transaction ID
        })
    
    # Sort by timestamp (handle None values)
    actions.sort(key=lambda x: x.get("timestamp") or "", reverse=True)
    
    return {
        "user": antelope_account,
        "project_id": project_id,
        "total_actions": len(actions),
        "actions": actions[:limit]
    }

@app.get("/api/admin/results/screening")
async def get_screening_results(
    project_id: str = Query(...),
    antelope_account: str = Query(...),
    result_type: str = Query("all", regex="^(all|human|llm)$"),
    gs_id: Optional[str] = Query(None)
):
    """Get screening results in readable format (admin only)."""
    database = get_db()
    check_roles(database, antelope_account, ["admin"])
    
    results = {
        "project_id": project_id,
        "papers": []
    }
    
    # Get gold standard papers
    gs_query = {"project_id": project_id}
    if gs_id:
        gs_query["gs_id"] = gs_id
    
    gs_papers = list(database[GOLD_STANDARD_COLLECTION].find(
        gs_query,
        {"_id": 0}
    ).sort("gs_id", 1))
    
    for paper in gs_papers:
        paper_result = {
            "gs_id": paper["gs_id"],
            "title": paper["title"],
            "year": paper.get("year"),
            "is_calibration": paper.get("is_calibration", False),
            "human_decisions": [],
            "llm_decisions": [],
            "resolution": None
        }
        
        # Get human decisions
        if result_type in ["all", "human"]:
            human_decisions = list(database[DECISIONS_COLLECTION].find(
                {"project_id": project_id, "gs_id": paper["gs_id"]},
                {"_id": 0}
            ))
            paper_result["human_decisions"] = human_decisions
            
            # Get resolution if exists
            resolution = database[RESOLUTIONS_COLLECTION].find_one(
                {"project_id": project_id, "gs_id": paper["gs_id"]},
                {"_id": 0}
            )
            if resolution:
                paper_result["resolution"] = resolution
        
        # Get LLM decisions
        if result_type in ["all", "llm"] and "llm_decisions" in database.list_collection_names():
            llm_decisions = list(database["llm_decisions"].find(
                {"project_id": project_id, "gs_id": paper["gs_id"]},
                {"_id": 0}
            ))
            paper_result["llm_decisions"] = llm_decisions
        
        results["papers"].append(paper_result)
    
    return results

@app.get("/api/admin/results/evaluation")
async def get_evaluation_results(
    project_id: str = Query(...),
    antelope_account: str = Query(...)
):
    """Get evaluation results in readable format (admin only)."""
    database = get_db()
    check_roles(database, antelope_account, ["admin"])
    
    if "evaluation_results" not in database.list_collection_names():
        return {"project_id": project_id, "results": [], "message": "No evaluations found"}
    
    results = list(database["evaluation_results"].find(
        {"project_id": project_id},
        {"_id": 0}
    ).sort([("recall_threshold_met", -1), ("wss_95", -1)]))
    
    return {
        "project_id": project_id,
        "total_results": len(results),
        "results": results
    }

@app.get("/api/admin/results/llm-jobs")
async def get_llm_screening_jobs(
    project_id: str = Query(...),
    antelope_account: str = Query(...)
):
    """Get LLM screening jobs and their results (admin only)."""
    database = get_db()
    check_roles(database, antelope_account, ["admin"])
    
    # Check if llm_jobs collection exists
    if "llm_jobs" not in database.list_collection_names():
        return {
            "project_id": project_id,
            "jobs": [],
            "message": "No LLM screening jobs found"
        }
    
    # Get all jobs for this project
    jobs = list(database["llm_jobs"].find(
        {"project_id": project_id},
        {"_id": 0}
    ).sort("start_time", -1))
    
    # For each job, get summary statistics
    for job in jobs:
        job_id = job.get("job_id")
        
        # Count decisions made by this job
        if "llm_decisions" in database.list_collection_names():
            decision_count = database["llm_decisions"].count_documents({
                "project_id": project_id,
                "job_id": job_id
            })
            job["decisions_count"] = decision_count
            
            # Get decision breakdown
            pipeline = [
                {"$match": {"project_id": project_id, "job_id": job_id}},
                {"$group": {
                    "_id": "$final_decision",
                    "count": {"$sum": 1}
                }}
            ]
            breakdown = list(database["llm_decisions"].aggregate(pipeline))
            job["decision_breakdown"] = {item["_id"]: item["count"] for item in breakdown}
        else:
            job["decisions_count"] = 0
            job["decision_breakdown"] = {}
    
    return {
        "project_id": project_id,
        "total_jobs": len(jobs),
        "jobs": jobs
    }

@app.get("/api/admin/results/llm-decisions")
async def get_llm_decisions_detailed(
    project_id: str = Query(...),
    antelope_account: str = Query(...),
    job_id: Optional[str] = Query(None),
    strategy: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    limit: int = Query(100, ge=10, le=1000)
):
    """Get detailed LLM screening decisions (admin only)."""
    database = get_db()
    check_roles(database, antelope_account, ["admin"])
    
    if "llm_decisions" not in database.list_collection_names():
        return {
            "project_id": project_id,
            "decisions": [],
            "message": "No LLM decisions found"
        }
    
    # Build query
    query = {"project_id": project_id}
    if job_id:
        query["job_id"] = job_id
    if strategy:
        query["strategy"] = strategy
    if model:
        query["model"] = model
    
    # Get decisions
    decisions = list(database["llm_decisions"].find(
        query,
        {"_id": 0}
    ).sort("created_at", -1).limit(limit))
    
    # Get summary statistics
    total_count = database["llm_decisions"].count_documents(query)
    
    pipeline = [
        {"$match": query},
        {"$group": {
            "_id": "$final_decision",
            "count": {"$sum": 1}
        }}
    ]
    breakdown = list(database["llm_decisions"].aggregate(pipeline))
    decision_breakdown = {item["_id"]: item["count"] for item in breakdown}
    
    return {
        "project_id": project_id,
        "total_decisions": total_count,
        "decision_breakdown": decision_breakdown,
        "decisions": decisions,
        "filters": {
            "job_id": job_id,
            "strategy": strategy,
            "model": model
        }
    }

# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="PaSSER-SR Screening API v4.0")
    parser.add_argument("--host", type=str, default="0.0.0.0")
    parser.add_argument("--port", type=int, default=9901)
    parser.add_argument("--mongo", type=str, default=DEFAULT_MONGO_URI)
    parser.add_argument("--db", type=str, default=DEFAULT_DB_NAME)
    parser.add_argument("--bc-endpoint", type=str, default=DEFAULT_BC_ENDPOINT)
    parser.add_argument("--bc-key", type=str, default=DEFAULT_BC_PRIVATE_KEY)
    parser.add_argument("--reload", action="store_true")
    
    args = parser.parse_args()
    
    global bc_endpoint, bc_private_key
    bc_endpoint = args.bc_endpoint
    bc_private_key = args.bc_key
    
    if not connect_to_mongodb(args.mongo, args.db):
        return
    
    print(f"\n{'='*60}")
    print("PaSSER-SR Screening API v4.0 (with Blockchain Audit)")
    print(f"{'='*60}")
    print(f"Port: {args.port}")
    print(f"MongoDB: {args.mongo}")
    print(f"Blockchain: {args.bc_endpoint}")
    print(f"{'='*60}\n")
    
    uvicorn.run(
        "screening_api:app" if args.reload else app,
        host=args.host,
        port=args.port,
        reload=args.reload
    )

# =============================================================================
# FEW-SHOT EXAMPLES ENDPOINTS (Phase 5)
# =============================================================================

def parse_reason_to_criteria(reason: str) -> dict:
    """
    Parse structured reason field into criteria components.
    
    Input format:
        Criteria met: IC1 (text); IC2 (text)
        Criteria violated: EC1 (text); EC2 (text)
        Notes: additional text
    
    Output:
        {
            "criteria_met": ["IC1", "IC2"],
            "criteria_violated": ["EC1", "EC2"],
            "reasoning": "additional text"
        }
    """
    import re
    
    result = {
        "criteria_met": [],
        "criteria_violated": [],
        "reasoning": ""
    }
    
    if not reason:
        return result
    
    # Parse "Criteria met: IC1 (...); IC2 (...)"
    met_match = re.search(r'Criteria met:\s*(.+?)(?:\n|$)', reason, re.IGNORECASE)
    if met_match:
        codes = re.findall(r'(IC\d+)', met_match.group(1))
        result["criteria_met"] = codes
    
    # Parse "Criteria violated: EC1 (...); EC2 (...)"
    violated_match = re.search(r'Criteria violated:\s*(.+?)(?:\n|$)', reason, re.IGNORECASE)
    if violated_match:
        codes = re.findall(r'(EC\d+)', violated_match.group(1))
        result["criteria_violated"] = codes
    
    # Parse "Notes: ..."
    notes_match = re.search(r'Notes:\s*(.+?)$', reason, re.DOTALL | re.IGNORECASE)
    if notes_match:
        result["reasoning"] = notes_match.group(1).strip()
    else:
        # If no structured format, use entire reason as reasoning
        if not met_match and not violated_match:
            result["reasoning"] = reason.strip()
    
    return result


@app.get("/api/fewshot/examples")
async def get_fewshot_examples(
    project_id: str = Query(...),
    antelope_account: str = Query(...)
):
    """
    Get few-shot examples from calibration set.
    Returns parsed screening decisions for calibration papers.
    """
    database = get_db()
    check_roles(database, antelope_account, ["screener", "resolver", "admin"])
    
    # Get calibration papers
    calibration_papers = list(database[GOLD_STANDARD_COLLECTION].find(
        {"project_id": project_id, "is_calibration": True},
        {"_id": 0, "gs_id": 1, "title": 1, "abstract": 1}
    ))
    
    if not calibration_papers:
        return {
            "project_id": project_id,
            "examples": [],
            "count": 0,
            "calibration_total": 0,
            "missing_decisions": [],
            "ready": False,
            "message": "No calibration papers found. Ensure is_calibration=true is set for calibration papers."
        }
    
    # Get decisions for calibration papers
    calibration_gs_ids = [p["gs_id"] for p in calibration_papers]
    
    decisions = {d["gs_id"]: d for d in database[DECISIONS_COLLECTION].find(
        {"project_id": project_id, "gs_id": {"$in": calibration_gs_ids}},
        {"_id": 0, "gs_id": 1, "decision": 1, "confidence": 1, "reason": 1}
    )}
    
    # Build few-shot examples
    examples = []
    missing = []
    
    for paper in calibration_papers:
        gs_id = paper["gs_id"]
        decision = decisions.get(gs_id)
        
        if not decision:
            missing.append(gs_id)
            continue
        
        # Parse reason into structured format
        parsed = parse_reason_to_criteria(decision.get("reason", ""))
        
        example = {
            "gs_id": gs_id,
            "title": paper.get("title", ""),
            "abstract": paper.get("abstract", ""),
            "decision": decision.get("decision", ""),
            "confidence": decision.get("confidence", ""),
            "criteria_met": parsed["criteria_met"],
            "criteria_violated": parsed["criteria_violated"],
            "reasoning": parsed["reasoning"]
        }
        examples.append(example)
    
    return {
        "project_id": project_id,
        "examples": examples,
        "count": len(examples),
        "calibration_total": len(calibration_papers),
        "missing_decisions": missing,
        "ready": len(missing) == 0 and len(examples) == len(calibration_papers) and len(examples) > 0
    }


@app.get("/api/fewshot/export")
async def export_fewshot_examples(
    project_id: str = Query(...),
    antelope_account: str = Query(...)
):
    """
    Export few-shot examples in format ready for LLM prompts.
    Returns clean format without internal IDs.
    """
    database = get_db()
    check_roles(database, antelope_account, ["admin"])
    
    # Reuse the get function logic
    result_data = await get_fewshot_examples(project_id, antelope_account)
    
    if not result_data.get("ready"):
        raise HTTPException(
            status_code=400, 
            detail=f"Few-shot examples not ready. Missing decisions for: {result_data.get('missing_decisions', [])}"
        )
    
    # Format for LLM prompt (remove gs_id, keep only needed fields)
    export_examples = []
    for ex in result_data["examples"]:
        export_examples.append({
            "title": ex["title"],
            "abstract": ex["abstract"],
            "decision": ex["decision"],
            "criteria_met": ex["criteria_met"],
            "criteria_violated": ex["criteria_violated"],
            "reasoning": ex["reasoning"]
        })
    
    return {
        "project_id": project_id,
        "examples": export_examples,
        "count": len(export_examples),
        "exported_at": datetime.utcnow().isoformat()
    }

if __name__ == "__main__":
    main()
