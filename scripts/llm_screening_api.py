#!/usr/bin/env python3
"""
PaSSER-SR LLM Screening API Service (v1.0)
==========================================
FastAPI backend for LLM-based screening with WebSocket real-time updates.
Optimized for Apple Silicon (MLX) with external SSD cache.

Port: 9902

Endpoints:
    GET  /api/llm/status              - Get service status and loaded models
    GET  /api/llm/models              - List available models
    POST /api/llm/models/load         - Load a model into memory
    POST /api/llm/models/unload       - Unload a model from memory
    GET  /api/llm/strategies          - List available strategies
    POST /api/llm/screen/start        - Start screening job
    POST /api/llm/screen/stop         - Stop running job
    GET  /api/llm/jobs                - List screening jobs
    GET  /api/llm/jobs/{job_id}       - Get job details
    GET  /api/llm/results/{job_id}    - Get screening results

WebSocket:
    /ws/llm/progress                  - Real-time progress updates

Author: PaSSER-SR Team
Date: January 2026
Version: 1.0
"""

import os
import sys
import json
import asyncio
import hashlib
import tempfile
import uuid
import re
import traceback
import psutil
import gc
from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum
from pathlib import Path
import logging
from dataclasses import dataclass, asdict, field
from collections import defaultdict
import threading
import time

# Import screening criteria constants
from screening_criteria_constants import (
    INCLUSION_CRITERIA_TEXT,
    EXCLUSION_CRITERIA_TEXT,
    format_reasoning_with_criteria,
    generate_criteria_prompt_section
)

# =============================================================================
# SSD CACHE CONFIGURATION - MUST BE BEFORE OTHER IMPORTS!
# =============================================================================

def setup_cache_directories(cache_volume: str = "/Volumes/LLM"):
    """Configure all cache directories on external SSD."""
    
    # HuggingFace model cache
    hf_cache_dir = f"{cache_volume}/ml_cache/huggingface"
    os.environ["HF_HOME"] = hf_cache_dir
    os.environ["HF_DATASETS_CACHE"] = f"{hf_cache_dir}/datasets"
    os.environ["HF_HUB_CACHE"] = f"{hf_cache_dir}/hub"
    os.environ["HUGGINGFACE_HUB_CACHE"] = f"{hf_cache_dir}/hub"
    os.environ["XDG_CACHE_HOME"] = hf_cache_dir
    
    # PyTorch cache
    torch_cache_dir = f"{cache_volume}/ml_cache/torch"
    os.environ["TORCH_HOME"] = torch_cache_dir
    os.environ["TORCH_EXTENSIONS_DIR"] = f"{torch_cache_dir}/extensions"
    
    # Temporary files
    temp_dir = f"{cache_volume}/ml_cache/tmp"
    os.environ["TMPDIR"] = temp_dir
    os.environ["TEMP"] = temp_dir
    os.environ["TMP"] = temp_dir
    
    # Shared memory
    shared_mem_dir = f"{cache_volume}/ml_cache/shm"
    os.environ["MULTIPROCESSING_SHAREDMEM_PREFIX"] = shared_mem_dir
    
    # NumPy memory-mapped arrays
    os.environ["NUMPY_MMAP_DIR"] = f"{temp_dir}/numpy_mmap"
    
    # MPS settings for Apple Silicon
    os.environ["PYTORCH_MPS_HIGH_WATERMARK_RATIO"] = "0.0"
    os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
    os.environ["PYTORCH_MPS_PREFER_METAL"] = "1"
    os.environ["PYTORCH_DISABLE_MPS_PARTITIONER"] = "1"
    os.environ["MPS_ALLOW_FALLBACK"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    
    # Create all directories
    directories = [
        hf_cache_dir,
        f"{hf_cache_dir}/hub",
        f"{hf_cache_dir}/datasets",
        f"{hf_cache_dir}/transformers",
        torch_cache_dir,
        f"{torch_cache_dir}/extensions",
        temp_dir,
        f"{temp_dir}/numpy_mmap",
        shared_mem_dir,
    ]
    
    for directory in directories:
        os.makedirs(directory, exist_ok=True)
    
    # Set Python's tempfile module
    tempfile.tempdir = temp_dir
    
    return {
        "hf_cache": hf_cache_dir,
        "torch_cache": torch_cache_dir,
        "temp_dir": temp_dir,
        "shared_mem": shared_mem_dir,
    }

# Get cache volume from environment or use default
CACHE_VOLUME = os.environ.get("LLM_CACHE_VOLUME", "/Volumes/LLM")

# CRITICAL: Setup cache directories NOW, before any imports!
# This ensures HuggingFace and other libraries use the external SSD cache
# Note: Expand ~ for paths that need it at setup
CACHE_DIRS = setup_cache_directories(str(Path(CACHE_VOLUME).expanduser()))

print(f"✓ Cache configured on: {CACHE_VOLUME}")

# =============================================================================
# NOW IMPORT MLX AND OTHER LIBRARIES
# =============================================================================

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field
import uvicorn

# MongoDB
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure

# Blockchain
try:
    import pyntelope
    BLOCKCHAIN_AVAILABLE = True
    print("✓ Pyntelope (blockchain) is available")
except ImportError:
    BLOCKCHAIN_AVAILABLE = False
    print("⚠ Pyntelope not available - install with: pip install pyntelope")

# MLX imports
try:
    from mlx_lm import load, generate
    MLX_AVAILABLE = True
    print("✓ MLX is available")
except ImportError:
    MLX_AVAILABLE = False
    print("⚠ MLX not available - install with: pip install mlx-lm")

# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017/")
DEFAULT_DB_NAME = os.environ.get("DB_NAME", "passer_sr")
RESULTS_DIR = os.environ.get("LLM_RESULTS_DIR", f"{CACHE_VOLUME}/screening_results")
# Expand ~ in RESULTS_DIR when creating the directory
os.makedirs(Path(RESULTS_DIR).expanduser(), exist_ok=True)

# Blockchain configuration
BLOCKCHAIN_ENABLED = os.environ.get("BLOCKCHAIN_ENABLED", "true").lower() == "true"
BLOCKCHAIN_ENDPOINT = os.environ.get("BLOCKCHAIN_ENDPOINT", "http://localhost:8033")
BLOCKCHAIN_CONTRACT = os.environ.get("BLOCKCHAIN_CONTRACT", "sraudit")
BLOCKCHAIN_PRIVATE_KEY = os.environ.get("BLOCKCHAIN_PRIVATE_KEY", "<YOUR_BLOCKCHAIN_PRIVATE_KEY>")

# =============================================================================
# BLOCKCHAIN LOGGING
# =============================================================================

def log_paper_decision_to_blockchain(decision_data: Dict) -> Optional[str]:
    """
    Log an individual paper screening decision to blockchain.
    This creates a transaction visible in the user's MyAction tab.
    
    Args:
        decision_data: Dictionary containing:
            - screener: Antelope account name (screener)
            - projectid: Project identifier (max 32 chars)
            - gsid: Paper ID (max 16 chars)
            - decision: INCLUDE, EXCLUDE, or UNCERTAIN
            - confidence: HIGH, MEDIUM, or LOW
            - model: LLM model used (max 32 chars)
            - strategy: Strategy used (max 16 chars)
            - jobid: Job identifier (max 32 chars)
            - datahash: Hash of decision data for verification
    
    Returns:
        Transaction ID string if successful, None otherwise
    """
    if not BLOCKCHAIN_ENABLED or not BLOCKCHAIN_AVAILABLE or not BLOCKCHAIN_PRIVATE_KEY:
        return None
    
    try:
        # Build blockchain action data for logllmdecision
        tx_data = [
            pyntelope.Data(name="screener", value=pyntelope.types.Name(decision_data["screener"])),
            pyntelope.Data(name="projectid", value=pyntelope.types.String(decision_data["projectid"][:32])),
            pyntelope.Data(name="gsid", value=pyntelope.types.String(decision_data["gsid"][:16])),
            pyntelope.Data(name="decision", value=pyntelope.types.String(decision_data["decision"])),
            pyntelope.Data(name="confidence", value=pyntelope.types.String(decision_data["confidence"])),
            pyntelope.Data(name="model", value=pyntelope.types.String(decision_data["model"][:32])),
            pyntelope.Data(name="strategy", value=pyntelope.types.String(decision_data["strategy"][:16])),
            pyntelope.Data(name="jobid", value=pyntelope.types.String(decision_data["jobid"][:32])),
            pyntelope.Data(name="datahash", value=pyntelope.types.String(decision_data["datahash"][:64])),
        ]
        
        # Create authorization
        auth = pyntelope.Authorization(actor=BLOCKCHAIN_CONTRACT, permission="active")
        
        # Create action (using NEW logllmdecision action for LLM screening)
        bc_action = pyntelope.Action(
            account=BLOCKCHAIN_CONTRACT,
            name="logllmdec",
            data=tx_data,
            authorization=[auth]
        )
        
        # Create and send transaction
        raw_transaction = pyntelope.Transaction(actions=[bc_action])
        net = pyntelope.Net(host=BLOCKCHAIN_ENDPOINT)
        linked_transaction = raw_transaction.link(net=net)
        signed_transaction = linked_transaction.sign(key=BLOCKCHAIN_PRIVATE_KEY)
        resp = signed_transaction.send()
        
        tx_id = resp.get("transaction_id", "unknown")
        return tx_id
        
    except Exception as e:
        print(f"✗ Paper decision blockchain error: {e}")
        return None


def log_llm_job_to_blockchain(job_data: Dict) -> Optional[str]:
    """
    Log an LLM screening job to the blockchain for immutability and audit trail.
    This creates a transaction for the completed job (visible in Job History).
    
    Args:
        job_data: Dictionary containing job details with keys:
            - username: Antelope account name (screener)
            - project_id: Project identifier
            - job_id: Unique job identifier
            - strategy: Screening strategy (S1-S5)
            - models: Comma-separated list of models used
            - prompt_mode: Prompt mode (e.g., "multi_agent")
            - papers_count: Number of papers screened
            - results: Optional results summary
    
    Returns:
        Transaction ID string if successful, None if blockchain disabled or error occurs
    """
    if not BLOCKCHAIN_ENABLED:
        print("ℹ️ Blockchain recording disabled")
        return None
    
    if not BLOCKCHAIN_AVAILABLE:
        print("⚠️ Blockchain library (pyntelope) not available")
        return None
    
    if not BLOCKCHAIN_PRIVATE_KEY:
        print("⚠️ Blockchain private key not configured")
        return None
    
    try:
        # Create data hash for integrity verification
        data_str = json.dumps(job_data, sort_keys=True)
        data_hash = hashlib.sha256(data_str.encode()).hexdigest()[:16]
        
        # Build blockchain action data
        tx_data = [
            pyntelope.Data(name="username", value=pyntelope.types.Name(job_data["username"])),
            pyntelope.Data(name="projectid", value=pyntelope.types.String(job_data["project_id"][:32])),
            pyntelope.Data(name="jobid", value=pyntelope.types.String(job_data["job_id"][:32])),
            pyntelope.Data(name="strategy", value=pyntelope.types.String(job_data["strategy"][:16])),
            pyntelope.Data(name="models", value=pyntelope.types.String(job_data["models"][:128])),
            pyntelope.Data(name="promptmode", value=pyntelope.types.String(job_data["prompt_mode"][:32])),
            pyntelope.Data(name="papercount", value=pyntelope.types.Uint32(job_data["papers_count"])),
            pyntelope.Data(name="datahash", value=pyntelope.types.String(data_hash)),
        ]
        
        # Create authorization
        auth = pyntelope.Authorization(actor=BLOCKCHAIN_CONTRACT, permission="active")
        
        # Create action (action name: "logllmjob")
        bc_action = pyntelope.Action(
            account=BLOCKCHAIN_CONTRACT,
            name="logllmjob",
            data=tx_data,
            authorization=[auth]
        )
        
        # Create and send transaction
        raw_transaction = pyntelope.Transaction(actions=[bc_action])
        net = pyntelope.Net(host=BLOCKCHAIN_ENDPOINT)
        linked_transaction = raw_transaction.link(net=net)
        signed_transaction = linked_transaction.sign(key=BLOCKCHAIN_PRIVATE_KEY)
        resp = signed_transaction.send()
        
        tx_id = resp.get("transaction_id", "unknown")
        print(f"✓ LLM Job logged to blockchain: {tx_id}")
        return tx_id
        
    except Exception as e:
        print(f"✗ Blockchain logging error: {e}")
        import traceback
        traceback.print_exc()
        return None

# Memory safety limits (in MB)
MAX_MEMORY_MB = int(os.environ.get("MAX_MEMORY_MB", "28000"))  # 28GB safety limit for 32GB Mac
MEMORY_WARNING_MB = int(os.environ.get("MEMORY_WARNING_MB", "24000"))  # Warn at 24GB

# =============================================================================
# LOGGING CONFIGURATION
# =============================================================================

def setup_logging():
    """Configure detailed logging for debugging."""
    log_dir = Path(RESULTS_DIR).expanduser() / "logs"
    log_dir.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"llm_screening_{timestamp}.log"
    
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )
    
    # Reduce MongoDB heartbeat spam
    logging.getLogger('pymongo').setLevel(logging.WARNING)
    logging.getLogger('pymongo.topology').setLevel(logging.WARNING)
    logging.getLogger('pymongo.serverSelection').setLevel(logging.WARNING)
    logging.getLogger('pymongo.connection').setLevel(logging.WARNING)
    logging.getLogger('pymongo.command').setLevel(logging.WARNING)
    
    return str(log_file)

# =============================================================================
# RESOURCE MONITORING
# =============================================================================

def get_memory_usage():
    """Get current memory usage in MB."""
    process = psutil.Process()
    return process.memory_info().rss / 1024 / 1024

def log_resource_usage(logger, context=""):
    """Log current resource usage."""
    mem_mb = get_memory_usage()
    logger.info(f"[RESOURCE] {context} - Memory: {mem_mb:.1f} MB")
    return mem_mb

def check_memory_limit(logger, context=""):
    """Check if memory usage is approaching limits."""
    mem_mb = get_memory_usage()
    
    if mem_mb > MAX_MEMORY_MB:
        logger.error(f"[MEMORY] CRITICAL - {context}: {mem_mb:.1f}MB exceeds limit {MAX_MEMORY_MB}MB")
        raise MemoryError(f"Memory limit exceeded: {mem_mb:.1f}MB > {MAX_MEMORY_MB}MB")
    
    if mem_mb > MEMORY_WARNING_MB:
        logger.warning(f"[MEMORY] WARNING - {context}: {mem_mb:.1f}MB approaching limit")
    
    return mem_mb

# =============================================================================
# FEW-SHOT EXAMPLES FROM DATABASE (Phase 5)
# =============================================================================

def get_fewshot_examples_from_db(project_id: str, database) -> List[Dict]:
    """
    Get few-shot examples directly from MongoDB calibration set.
    
    Args:
        project_id: Project identifier
        database: MongoDB database connection (already connected)
    
    Returns:
        List of few-shot example dictionaries ready for LLM prompts
    """
    import re
    
    # Create logger inside function
    func_logger = logging.getLogger("FewShot")
    
    def parse_reason_to_criteria(reason: str) -> dict:
        """Parse structured reason field into criteria components."""
        result = {"criteria_met": [], "criteria_violated": [], "reasoning": ""}
        if not reason:
            return result
        
        # Parse "Criteria met: IC1 (...); IC2 (...)"
        met_match = re.search(r'Criteria met:\s*(.+?)(?:\n|$)', reason, re.IGNORECASE)
        if met_match:
            result["criteria_met"] = re.findall(r'(IC\d+)', met_match.group(1))
        
        # Parse "Criteria violated: EC1 (...); EC2 (...)"
        violated_match = re.search(r'Criteria violated:\s*(.+?)(?:\n|$)', reason, re.IGNORECASE)
        if violated_match:
            result["criteria_violated"] = re.findall(r'(EC\d+)', violated_match.group(1))
        
        # Parse "Notes: ..."
        notes_match = re.search(r'Notes:\s*(.+?)$', reason, re.DOTALL | re.IGNORECASE)
        if notes_match:
            result["reasoning"] = notes_match.group(1).strip()
        elif not met_match and not violated_match:
            result["reasoning"] = reason.strip()
        
        return result
    
    try:
        # database is already a MongoDB database connection (self.db)
        # No need to create new MongoClient
        
        # Get calibration papers
        calibration_papers = {
            p["gs_id"]: p for p in database["gold_standard"].find(
                {"project_id": project_id, "is_calibration": True},
                {"_id": 0, "gs_id": 1, "title": 1, "abstract": 1}
            )
        }
        
        if not calibration_papers:
            func_logger.warning(f"No calibration papers found for project {project_id}")
            return []
        
        # Get decisions for calibration papers
        decisions = list(database["screening_decisions"].find(
            {"project_id": project_id, "gs_id": {"$in": list(calibration_papers.keys())}},
            {"_id": 0, "gs_id": 1, "decision": 1, "confidence": 1, "reason": 1}
        ))
        
        if not decisions:
            func_logger.warning(f"No calibration decisions found for project {project_id}")
            return []
        
        # Build examples
        examples = []
        for decision in decisions:
            gs_id = decision["gs_id"]
            paper = calibration_papers.get(gs_id)
            if not paper:
                continue
            
            parsed = parse_reason_to_criteria(decision.get("reason", ""))
            
            examples.append({
                "title": paper.get("title", ""),
                "abstract": paper.get("abstract", ""),
                "decision": decision.get("decision", ""),
                "criteria_met": parsed["criteria_met"],
                "criteria_violated": parsed["criteria_violated"],
                "reasoning": parsed["reasoning"]
            })
        
        func_logger.info(f"Loaded {len(examples)} few-shot examples for project {project_id}")
        return examples
        
    except Exception as e:
        func_logger.error(f"Failed to load few-shot examples: {e}")
        return []
    
# =============================================================================
# MODEL CONFIGURATIONS
# =============================================================================

@dataclass
class ModelConfig:
    """Configuration for a single LLM model."""
    name: str
    model_id: str
    prompt_template: str  # "llama", "mistral", "granite"
    description: str = ""
    
AVAILABLE_MODELS = {
    "mistral-7b": ModelConfig(
        name="Mistral 7B Instruct v0.3",
        model_id="mlx-community/Mistral-7B-Instruct-v0.3-4bit",
        prompt_template="mistral",
        description="Fast, efficient general-purpose model"
    ),
    "llama-8b": ModelConfig(
        name="LLaMA 3.1 8B Instruct",
        model_id="mlx-community/Meta-Llama-3.1-8B-Instruct-4bit",
        prompt_template="llama",
        description="Meta's latest instruction-tuned model"
    ),
    "granite-8b": ModelConfig(
        name="Granite 3.3 8B Instruct",
        model_id="mlx-community/granite-3.3-8b-instruct-4bit",
        prompt_template="granite",
        description="IBM's enterprise-focused model"
    ),
    "qwen-7b": ModelConfig(
        name="Qwen 2.5 7B Instruct",
        model_id="mlx-community/Qwen2.5-7B-Instruct-4bit",
        prompt_template="qwen",
        description="Alibaba's multilingual model (alternative)"
    ),
}

# Confidence mapping
CONFIDENCE_MAP = {"HIGH": 0.9, "MEDIUM": 0.7, "LOW": 0.5}

# NOTE: Criteria text and formatting functions imported from screening_criteria_constants.py
# This ensures consistency between LLM and Human screening modules

# =============================================================================
# ENUMS AND MODELS
# =============================================================================

class Decision(str, Enum):
    INCLUDE = "INCLUDE"
    EXCLUDE = "EXCLUDE"
    UNCERTAIN = "UNCERTAIN"

class Confidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"

class Strategy(str, Enum):
    S1_SINGLE = "S1_SINGLE"
    S2_MAJORITY = "S2_MAJORITY"
    S3_RECALL_OPT = "S3_RECALL_OPT"
    S4_CONFIDENCE = "S4_CONFIDENCE"
    S5_TWO_STAGE = "S5_TWO_STAGE"

class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class DataSource(str, Enum):
    CORPUS = "corpus"
    GOLD_STANDARD = "gold_standard"

class PromptMode(str, Enum):
    ZERO_SHOT = "zero_shot"
    FEW_SHOT = "few_shot"

# Request/Response Models
class LoadModelRequest(BaseModel):
    model_key: str

class StartScreeningRequest(BaseModel):
    project_id: str
    data_source: DataSource
    strategies: List[Strategy]
    models: List[str]
    prompt_mode: PromptMode = PromptMode.ZERO_SHOT
    few_shot_examples: Optional[List[Dict]] = None
    output_filename: Optional[str] = None
    evaluation_only: bool = True      # NEW: Exclude calibration papers from Gold Standard
    save_to_mongodb: bool = True      # NEW: Save results to llm_decisions collection
    antelope_account: Optional[str] = None  # NEW: User who initiated the screening
    resume_job_id: Optional[str] = None  # NEW: Resume from specific job (skips completed papers)
    s5_model_roles: Optional[Dict[str, Any]] = None  # {"fast_filter": "llama-8b", "debate": ["mistral-7b", "qwen-7b"]}

class StopJobRequest(BaseModel):
    job_id: str


class EvaluateJobRequest(BaseModel):
    """Request for Variant 1: metrics for a specific job"""
    uncertain_treatment: str = Field(
        default="INCLUDE",
        description="How to treat UNCERTAIN: 'INCLUDE' (conservative) or 'EXCLUDE'"
    )
    save_to_db: bool = Field(
        default=True,
        description="Whether to save results to MongoDB"
    )


class EvaluateCompareRequest(BaseModel):
    """Request for Variant 2: comparative metrics"""
    project_id: str = Field(..., description="Project ID")
    uncertain_treatment: str = Field(
        default="INCLUDE",
        description="How to treat UNCERTAIN: 'INCLUDE' (conservative) or 'EXCLUDE'"
    )
    filter_strategies: Optional[List[str]] = Field(
        default=None,
        description="Filter by strategies (e.g. ['S1_SINGLE', 'S2_MAJORITY'])"
    )
    filter_models: Optional[List[str]] = Field(
        default=None,
        description="Filter by models (e.g. ['llama-8b', 'mistral-7b'])"
    )
    filter_prompt_modes: Optional[List[str]] = Field(
        default=None,
        description="Filter by prompt mode (e.g. ['few_shot'])"
    )
    job_ids: Optional[List[str]] = Field(
        default=None,
        description="Filter by specific job IDs"
    )
    save_to_db: bool = Field(
        default=True,
        description="Whether to save results to MongoDB"
    )

# Collection names for evaluation
GOLD_STANDARD_COLLECTION = "gold_standard"
DECISIONS_COLLECTION = "screening_decisions"
RESOLUTIONS_COLLECTION = "resolutions"
LLM_DECISIONS_COLLECTION = "llm_decisions"
EVALUATION_RESULTS_COLLECTION = "evaluation_results"

# =============================================================================
# PROMPTS
# =============================================================================

# System prompt is now dynamically generated to use centralized criteria
SYSTEM_PROMPT = f"""You are an expert systematic review screener. Your task is to classify academic papers based on title and abstract.

{generate_criteria_prompt_section()}

You must respond ONLY in valid JSON format:
{{
    "decision": "INCLUDE" or "EXCLUDE" or "UNCERTAIN",
    "confidence": "HIGH" or "MEDIUM" or "LOW",
    "criteria_met": ["IC1", "IC2", ...],
    "criteria_violated": ["EC1", "EC2", ...],
    "reasoning": "Brief explanation (max 100 words)"
}}"""

SCREENING_PROMPT = """Evaluate this paper for inclusion in a systematic review on blockchain-based electoral systems.

TITLE: {title}

ABSTRACT: {abstract}

Based on the inclusion/exclusion criteria, provide your decision in JSON format."""

FEW_SHOT_TEMPLATE = """
EXAMPLES:
{examples}

Now evaluate this paper:"""

EXAMPLE_TEMPLATE = """
Example {n}:
Title: "{title}"
Abstract: "{abstract}"
Decision: {decision}
Criteria: {criteria}
Reasoning: {reasoning}
"""

# =============================================================================
# MODEL MANAGER
# =============================================================================

class MLXModelManager:
    """Manages loading and inference for MLX models."""
    
    def __init__(self, memory_efficient_mode: bool = True):
        self.models: Dict[str, tuple] = {}  # {key: (model, tokenizer, config)}
        self.loading_lock = threading.Lock()
        self.logger = logging.getLogger("MLXModelManager")
        self.memory_efficient_mode = memory_efficient_mode  # Auto-load/unload for low RAM
        
        if memory_efficient_mode:
            self.logger.info("🔋 Memory-efficient mode ENABLED - models will load/unload on-demand")
        else:
            self.logger.info("⚡ Performance mode ENABLED - models stay loaded")
    
    def get_loaded_models(self) -> List[str]:
        """Return list of currently loaded model keys."""
        return list(self.models.keys())
    
    def is_loaded(self, model_key: str) -> bool:
        """Check if model is loaded."""
        return model_key in self.models
    
    def load_model(self, model_key: str) -> Dict[str, Any]:
        """Load a model into memory."""
        if model_key not in AVAILABLE_MODELS:
            raise ValueError(f"Unknown model: {model_key}")
        
        if model_key in self.models:
            return {"status": "already_loaded", "model": model_key}
        
        config = AVAILABLE_MODELS[model_key]
        
        with self.loading_lock:
            self.logger.info(f"Loading {config.name}...")
            start = time.time()
            
            try:
                model, tokenizer = load(config.model_id)
                load_time = time.time() - start
                
                self.models[model_key] = (model, tokenizer, config)
                self.logger.info(f"✓ Loaded {config.name} in {load_time:.1f}s")
                
                return {
                    "status": "loaded",
                    "model": model_key,
                    "name": config.name,
                    "load_time": load_time
                }
            except Exception as e:
                self.logger.error(f"Failed to load {model_key}: {e}")
                raise
    
    def unload_model(self, model_key: str) -> Dict[str, Any]:
        """Unload a model to free memory."""
        if model_key not in self.models:
            return {"status": "not_loaded", "model": model_key}
        
        mem_before = get_memory_usage()
        del self.models[model_key]
        
        # Aggressive garbage collection to free memory immediately
        gc.collect()
        
        mem_after = get_memory_usage()
        mem_freed = mem_before - mem_after
        self.logger.info(f"Unloaded {model_key} - Freed {mem_freed:.1f}MB (was {mem_before:.1f}MB, now {mem_after:.1f}MB)")
        
        return {
            "status": "unloaded", 
            "model": model_key,
            "memory_freed_mb": mem_freed,
            "memory_after_mb": mem_after
        }
    
    def generate(
        self,
        model_key: str,
        prompt: str,
        max_tokens: int = 512,
        temperature: float = 0.3,
        auto_unload: bool = False,
    ) -> tuple:
        """Generate text. Returns (text, elapsed_time, approx_tokens).
        
        Args:
            auto_unload: If True, unload model after generation (memory-efficient mode)
        """
        if model_key not in self.models:
            raise ValueError(f"Model {model_key} not loaded")
        
        model, tokenizer, config = self.models[model_key]
        
        start = time.time()
        # Note: Some MLX models don't support temperature parameter
        try:
            response = generate(
                model,
                tokenizer,
                prompt=prompt,
                max_tokens=max_tokens,
                temp=temperature,
                verbose=False,
            )
        except TypeError:
            # Fallback: generate without temperature if not supported
            response = generate(
                model,
                tokenizer,
                prompt=prompt,
                max_tokens=max_tokens,
                verbose=False,
            )
        elapsed = time.time() - start
        
        tokens = len(response.split()) * 1.3
        
        # Auto-unload if requested (memory-efficient mode)
        if auto_unload:
            self.logger.info(f"🗑️  Auto-unloading {model_key} to free memory")
            self.unload_model(model_key)
        
        return response, elapsed, int(tokens)

# =============================================================================
# SCREENING ENGINE
# =============================================================================

class ScreeningEngine:
    """LLM screening engine with strategy support."""
    
    def __init__(self, model_manager: MLXModelManager):
        self.model_manager = model_manager
        self.logger = logging.getLogger("ScreeningEngine")
    
    def _build_prompt(
        self,
        title: str,
        abstract: str,
        model_key: str,
        prompt_mode: PromptMode = PromptMode.ZERO_SHOT,
        few_shot_examples: List[Dict] = None,
    ) -> str:
        """Build the full prompt for a model."""
        config = AVAILABLE_MODELS[model_key]
        
        # Build screening content
        screening_content = SCREENING_PROMPT.format(title=title, abstract=abstract)
        
        # Add few-shot examples if provided
        if prompt_mode == PromptMode.FEW_SHOT and few_shot_examples:
            examples_text = ""
            for i, ex in enumerate(few_shot_examples, 1):
                examples_text += EXAMPLE_TEMPLATE.format(
                    n=i,
                    title=ex.get("title", ""),
                    abstract=ex.get("abstract", "")[:200] + "...",
                    decision=ex.get("decision", ""),
                    criteria=", ".join(ex.get("criteria_met", []) + ex.get("criteria_violated", [])),
                    reasoning=ex.get("reasoning", ""),
                )
            screening_content = FEW_SHOT_TEMPLATE.format(examples=examples_text) + "\n" + screening_content
        
        # Apply model-specific template
        if config.prompt_template == "llama":
            return f"""<|begin_of_text|><|start_header_id|>system<|end_header_id|>

{SYSTEM_PROMPT}<|eot_id|><|start_header_id|>user<|end_header_id|>

{screening_content}<|eot_id|><|start_header_id|>assistant<|end_header_id|>

"""
        elif config.prompt_template == "mistral":
            return f"""[INST] {SYSTEM_PROMPT}

{screening_content} [/INST]"""
        else:  # granite, qwen, etc.
            return f"""<|system|>
{SYSTEM_PROMPT}<|end|>
<|user|>
{screening_content}<|end|>
<|assistant|>
"""
    
    def _parse_response(self, raw_output: str) -> Dict:
        """Parse LLM JSON response and format reasoning with criteria text."""
        # Try to find JSON
        json_match = re.search(r'\{[^{}]*\}', raw_output, re.DOTALL)
        
        if json_match:
            try:
                data = json.loads(json_match.group())
                
                # Extract raw values
                decision = data.get("decision", "UNCERTAIN").upper()
                confidence = data.get("confidence", "LOW").upper()
                criteria_met = data.get("criteria_met", [])
                criteria_violated = data.get("criteria_violated", [])
                original_reasoning = data.get("reasoning", "")
                
                # Format reasoning with criteria text (unified format)
                formatted_reasoning = format_reasoning_with_criteria(
                    criteria_met, criteria_violated, original_reasoning
                )
                
                return {
                    "decision": decision,
                    "confidence": confidence,
                    "criteria_met": criteria_met,
                    "criteria_violated": criteria_violated,
                    "reasoning": formatted_reasoning,  # Now includes criteria text
                }
            except json.JSONDecodeError:
                pass
        
        # Fallback parsing (no criteria available)
        raw_upper = raw_output.upper()
        decision = "UNCERTAIN"
        if "INCLUDE" in raw_upper and "EXCLUDE" not in raw_upper:
            decision = "INCLUDE"
        elif "EXCLUDE" in raw_upper:
            decision = "EXCLUDE"
        
        confidence = "LOW"
        if "HIGH" in raw_upper:
            confidence = "HIGH"
        elif "MEDIUM" in raw_upper:
            confidence = "MEDIUM"
        
        return {
            "decision": decision,
            "confidence": confidence,
            "criteria_met": [],
            "criteria_violated": [],
            "reasoning": f"Notes: {raw_output[:200]}",  # Prefix with Notes for consistency
        }
    
    def _call_agent(
        self,
        model_key: str,
        title: str,
        abstract: str,
        prompt_mode: PromptMode = PromptMode.ZERO_SHOT,
        few_shot_examples: List[Dict] = None,
        paper_id: str = "unknown",
        paper_index: int = -1,
        lazy_load: bool = False,
    ) -> Dict:
        """Call a single agent with detailed error handling.
        
        Args:
            lazy_load: If True, load model before call and unload after (memory-efficient)
        """
        self.logger.debug(f"[CALL_AGENT] Starting - Model: {model_key}, Paper: {paper_id} (#{paper_index})")
        
        # Log memory before call
        mem_before = get_memory_usage()
        self.logger.debug(f"[CALL_AGENT] Memory before: {mem_before:.1f} MB")
        
        # Lazy loading: load model if not already loaded
        model_was_loaded = self.model_manager.is_loaded(model_key)
        if lazy_load and not model_was_loaded:
            self.logger.info(f"⚡ Lazy-loading {model_key} for paper {paper_id}...")
            try:
                self.model_manager.load_model(model_key)
            except Exception as e:
                self.logger.error(f"Failed to lazy-load {model_key}: {e}")
                raise
        
        try:
            prompt = self._build_prompt(title, abstract, model_key, prompt_mode, few_shot_examples)
            prompt_len = len(prompt)
            self.logger.debug(f"[CALL_AGENT] Prompt built - Length: {prompt_len} chars")
            
            self.logger.debug(f"[CALL_AGENT] Generating with model {model_key}...")
            # Auto-unload if in lazy_load mode
            raw_output, elapsed, tokens = self.model_manager.generate(
                model_key, 
                prompt,
                auto_unload=lazy_load
            )
            
            mem_after = get_memory_usage()
            mem_delta = mem_after - mem_before
            self.logger.debug(f"[CALL_AGENT] Generation complete - Time: {elapsed:.2f}s, Tokens: {tokens}, Memory delta: {mem_delta:.1f} MB")
            
            self.logger.debug(f"[CALL_AGENT] Parsing response...")
            parsed = self._parse_response(raw_output)
            
            result = {
                "model": model_key,
                "model_name": AVAILABLE_MODELS[model_key].name,
                **parsed,
                "raw_output": raw_output,
                "inference_time": elapsed,
                "tokens": tokens,
                "memory_delta_mb": mem_delta,
            }
            
            self.logger.info(f"[CALL_AGENT] SUCCESS - Model: {model_key}, Paper: {paper_id}, Decision: {parsed['decision']}, Time: {elapsed:.2f}s")
            return result
            
        except Exception as e:
            mem_after = get_memory_usage()
            error_trace = traceback.format_exc()
            self.logger.error(f"[CALL_AGENT] FAILED - Model: {model_key}, Paper: {paper_id} (#{paper_index})")
            self.logger.error(f"[CALL_AGENT] Error: {str(e)}")
            self.logger.error(f"[CALL_AGENT] Memory: {mem_before:.1f} -> {mem_after:.1f} MB")
            self.logger.error(f"[CALL_AGENT] Traceback:\n{error_trace}")
            
            return {
                "model": model_key,
                "model_name": AVAILABLE_MODELS[model_key].name,
                "decision": "UNCERTAIN",
                "confidence": "LOW",
                "criteria_met": [],
                "criteria_violated": [],
                "reasoning": f"Error: {str(e)}",
                "raw_output": "",
                "inference_time": 0,
                "tokens": 0,
                "error": str(e),
                "error_traceback": error_trace,
                "memory_delta_mb": mem_after - mem_before,
            }
    
    def screen_single(self, paper: Dict, model_key: str, stop_check=None, **kwargs) -> Dict:
        """S1: Single-agent screening."""
        # Extract these to avoid duplicate keyword arguments
        paper_id = kwargs.pop('paper_id', 'unknown')
        paper_index = kwargs.pop('paper_index', -1)
        
        self.logger.info(f"[S1_SINGLE] Starting - Paper: {paper_id} (#{paper_index}), Model: {model_key}")
        
        # Memory-efficient mode: load model on demand
        lazy_load = self.model_manager.memory_efficient_mode
        if lazy_load:
            self.logger.info(f"🔋 S1_SINGLE using lazy loading (memory-efficient)")
        
        # Check for stop request
        if stop_check and stop_check():
            self.logger.warning(f"[S1_SINGLE] STOP REQUESTED - Paper: {paper_id}")
            raise InterruptedError("Stop requested during S1_SINGLE")
        
        response = self._call_agent(
            model_key, 
            paper["title"], 
            paper["abstract"], 
            paper_id=paper_id,
            paper_index=paper_index,
            lazy_load=lazy_load,
            **kwargs
        )
        
        self.logger.info(f"[S1_SINGLE] Complete - Paper: {paper_id}, Decision: {response['decision']}")
        
        return {
            "strategy": "S1_SINGLE",
            "final_decision": response["decision"],
            "final_confidence": response["confidence"],
            "agent_responses": [response],
            "total_time": response["inference_time"],
        }
    
    def screen_majority(self, paper: Dict, models: List[str], stop_check=None, **kwargs) -> Dict:
        """S2: Majority voting with stop check support."""
        # Extract these to avoid duplicate keyword arguments
        paper_id = kwargs.pop('paper_id', 'unknown')
        paper_index = kwargs.pop('paper_index', -1)
        
        self.logger.info(f"[S2_MAJORITY] Starting - Paper: {paper_id} (#{paper_index}), Models: {models}")
        log_resource_usage(self.logger, f"S2_MAJORITY start for paper #{paper_index}")
        
        # Memory-efficient mode: load one model at a time
        lazy_load = self.model_manager.memory_efficient_mode
        if lazy_load:
            self.logger.info(f"🔋 S2_MAJORITY using lazy loading (memory-efficient)")
        
        responses = []
        total_time = 0
        
        for i, model_key in enumerate(models, 1):
            # Check for stop request
            if stop_check and stop_check():
                self.logger.warning(f"[S2_MAJORITY] STOP REQUESTED - Paper: {paper_id}, Agent {i}/{len(models)}")
                raise InterruptedError("Stop requested during S2_MAJORITY")
            
            # Check memory before loading next agent
            try:
                check_memory_limit(self.logger, f"S2 before agent {i}/{len(models)}")
            except MemoryError as me:
                self.logger.error(f"[S2_MAJORITY] Memory limit reached before agent {i}, stopping")
                raise
            
            self.logger.debug(f"[S2_MAJORITY] Calling agent {i}/{len(models)}: {model_key}")
            
            try:
                response = self._call_agent(
                    model_key, 
                    paper["title"], 
                    paper["abstract"], 
                    paper_id=paper_id,
                    paper_index=paper_index,
                    lazy_load=lazy_load,
                    **kwargs
                )
                responses.append(response)
                total_time += response["inference_time"]
                
                self.logger.info(f"[S2_MAJORITY] Agent {i}/{len(models)} complete - Decision: {response['decision']}, Time: {response['inference_time']:.2f}s")
                
                # Small delay and gc between agents to stabilize memory
                if i < len(models):  # Not after last agent
                    time.sleep(0.5)
                    gc.collect()
                
            except Exception as e:
                self.logger.error(f"[S2_MAJORITY] Agent {i}/{len(models)} ({model_key}) failed: {e}")
                # Continue with remaining agents even if one fails
                responses.append({
                    "model": model_key,
                    "model_name": AVAILABLE_MODELS.get(model_key, {}).name if model_key in AVAILABLE_MODELS else model_key,
                    "decision": "UNCERTAIN",
                    "confidence": "LOW",
                    "criteria_met": [],
                    "criteria_violated": [],
                    "reasoning": f"Agent failed: {str(e)}",
                    "raw_output": "",
                    "inference_time": 0,
                    "tokens": 0,
                    "error": str(e),
                })
        
        self.logger.debug(f"[S2_MAJORITY] All agents complete - Aggregating votes")
        
        # Count votes
        votes = {"INCLUDE": 0, "EXCLUDE": 0, "UNCERTAIN": 0}
        for r in responses:
            votes[r["decision"]] += 1
        
        if votes["INCLUDE"] >= 2:
            final_decision = "INCLUDE"
        elif votes["EXCLUDE"] >= 2:
            final_decision = "EXCLUDE"
        else:
            final_decision = "UNCERTAIN"
        
        # Average confidence
        conf_values = [CONFIDENCE_MAP.get(r["confidence"], 0.5) for r in responses]
        avg_conf = sum(conf_values) / len(conf_values) if conf_values else 0.5
        final_confidence = "HIGH" if avg_conf >= 0.85 else "MEDIUM" if avg_conf >= 0.65 else "LOW"
        
        self.logger.info(f"[S2_MAJORITY] Complete - Paper: {paper_id}, Final: {final_decision} ({final_confidence}), Votes: {votes}, Time: {total_time:.2f}s")
        log_resource_usage(self.logger, f"S2_MAJORITY end for paper #{paper_index}")
        
        return {
            "strategy": "S2_MAJORITY",
            "final_decision": final_decision,
            "final_confidence": final_confidence,
            "agent_responses": responses,
            "aggregation": {"votes": votes, "avg_confidence": avg_conf},
            "total_time": total_time,
        }
    
    def screen_recall_optimized(self, paper: Dict, models: List[str], stop_check=None, **kwargs) -> Dict:
        """S3: Recall-optimized (any INCLUDE = INCLUDE)."""
        # Extract these to avoid duplicate keyword arguments
        paper_id = kwargs.pop('paper_id', 'unknown')
        paper_index = kwargs.pop('paper_index', -1)
        
        self.logger.info(f"[S3_RECALL_OPT] Starting - Paper: {paper_id} (#{paper_index})")
        
        # Memory-efficient mode: load one model at a time
        lazy_load = self.model_manager.memory_efficient_mode
        if lazy_load:
            self.logger.info(f"🔋 S3_RECALL_OPT using lazy loading (memory-efficient)")
        
        responses = []
        total_time = 0
        
        for i, model_key in enumerate(models, 1):
            # Check for stop request
            if stop_check and stop_check():
                self.logger.warning(f"[S3_RECALL_OPT] STOP REQUESTED - Paper: {paper_id}, Agent {i}/{len(models)}")
                raise InterruptedError("Stop requested during S3_RECALL_OPT")
            
            # Check memory
            try:
                check_memory_limit(self.logger, f"S3 before agent {i}/{len(models)}")
            except MemoryError:
                self.logger.error(f"[S3_RECALL_OPT] Memory limit reached, stopping")
                raise
            
            response = self._call_agent(
                model_key, 
                paper["title"], 
                paper["abstract"],
                paper_id=paper_id,
                paper_index=paper_index,
                lazy_load=lazy_load,
                **kwargs
            )
            responses.append(response)
            total_time += response["inference_time"]
            
            # Cleanup between agents
            if i < len(models):
                time.sleep(0.5)
                gc.collect()
        
        has_include = any(r["decision"] == "INCLUDE" for r in responses)
        has_uncertain = any(r["decision"] == "UNCERTAIN" for r in responses)
        
        if has_include:
            final_decision = "INCLUDE"
        elif has_uncertain:
            final_decision = "UNCERTAIN"
        else:
            final_decision = "EXCLUDE"
        
        supporting = [r for r in responses if r["decision"] == final_decision]
        if supporting:
            max_conf = max(CONFIDENCE_MAP.get(r["confidence"], 0.5) for r in supporting)
        else:
            max_conf = 0.5
        final_confidence = "HIGH" if max_conf >= 0.85 else "MEDIUM" if max_conf >= 0.65 else "LOW"
        
        return {
            "strategy": "S3_RECALL_OPT",
            "final_decision": final_decision,
            "final_confidence": final_confidence,
            "agent_responses": responses,
            "aggregation": {"has_include": has_include, "logic": "OR"},
            "total_time": total_time,
        }
    
    def screen_confidence_weighted(self, paper: Dict, models: List[str], stop_check=None, **kwargs) -> Dict:
        """S4: Confidence-weighted aggregation."""
        # Extract these to avoid duplicate keyword arguments
        paper_id = kwargs.pop('paper_id', 'unknown')
        paper_index = kwargs.pop('paper_index', -1)
        
        self.logger.info(f"[S4_CONFIDENCE] Starting - Paper: {paper_id} (#{paper_index})")
        
        # Memory-efficient mode: load one model at a time
        lazy_load = self.model_manager.memory_efficient_mode
        if lazy_load:
            self.logger.info(f"🔋 S4_CONFIDENCE using lazy loading (memory-efficient)")
        
        responses = []
        total_time = 0
        
        for i, model_key in enumerate(models, 1):
            # Check for stop request
            if stop_check and stop_check():
                self.logger.warning(f"[S4_CONFIDENCE] STOP REQUESTED - Paper: {paper_id}, Agent {i}/{len(models)}")
                raise InterruptedError("Stop requested during S4_CONFIDENCE")
            
            # Check memory
            try:
                check_memory_limit(self.logger, f"S4 before agent {i}/{len(models)}")
            except MemoryError:
                self.logger.error(f"[S4_CONFIDENCE] Memory limit reached, stopping")
                raise
            
            response = self._call_agent(
                model_key, 
                paper["title"], 
                paper["abstract"],
                paper_id=paper_id,
                paper_index=paper_index,
                lazy_load=lazy_load,
                **kwargs
            )
            responses.append(response)
            total_time += response["inference_time"]
            
            # Cleanup between agents
            if i < len(models):
                time.sleep(0.5)
                gc.collect()
        
        weighted_score = 0
        total_weight = 0
        
        for r in responses:
            weight = CONFIDENCE_MAP.get(r["confidence"], 0.5)
            total_weight += weight
            if r["decision"] == "INCLUDE":
                weighted_score += weight
            elif r["decision"] == "EXCLUDE":
                weighted_score -= weight
        
        normalized = weighted_score / total_weight if total_weight > 0 else 0
        
        if normalized > 0.2:
            final_decision = "INCLUDE"
        elif normalized < -0.2:
            final_decision = "EXCLUDE"
        else:
            final_decision = "UNCERTAIN"
        
        decisions = [r["decision"] for r in responses]
        if all(d == final_decision for d in decisions):
            final_confidence = "HIGH"
        elif decisions.count(final_decision) >= 2:
            final_confidence = "MEDIUM"
        else:
            final_confidence = "LOW"
        
        return {
            "strategy": "S4_CONFIDENCE",
            "final_decision": final_decision,
            "final_confidence": final_confidence,
            "agent_responses": responses,
            "aggregation": {"weighted_score": weighted_score, "normalized": normalized},
            "total_time": total_time,
        }
    
    def screen_two_stage(self, paper: Dict, models: List[str], stop_check=None, 
                        s5_model_roles: Dict = None, **kwargs) -> Dict:
        """S5: Two-stage filtering with debate.
        
        Args:
            s5_model_roles: Optional role assignment dict:
                {"fast_filter": "llama-8b", "debate": ["mistral-7b", "qwen-7b"]}
                If None, falls back to models[0] as fast_filter.
        """
        paper_id = kwargs.pop('paper_id', 'unknown')
        paper_index = kwargs.pop('paper_index', -1)
        
        self.logger.info(f"[S5_TWO_STAGE] Starting - Paper: {paper_id} (#{paper_index})")
        
        # Memory-efficient mode: load one model at a time
        lazy_load = self.model_manager.memory_efficient_mode
        if lazy_load:
            self.logger.info(f"📋 S5_TWO_STAGE using lazy loading (memory-efficient)")
        
        # Role-based model assignment
        if s5_model_roles and isinstance(s5_model_roles, dict):
            fast_model = s5_model_roles.get("fast_filter", models[0])
            debate_models = s5_model_roles.get("debate", [])
            if isinstance(debate_models, str):
                debate_models = [debate_models]
            # Fallback: if debate is empty, use remaining models
            if not debate_models:
                debate_models = [m for m in models if m != fast_model]
            other_models = debate_models if debate_models else models
            self.logger.info(f"[S5_TWO_STAGE] Role assignment: fast_filter={fast_model}, debate={other_models}")
        else:
            fast_model = models[0]
            other_models = models[1:] if len(models) > 1 else models
            self.logger.info(f"[S5_TWO_STAGE] Default assignment: fast_filter={fast_model}, debate={other_models}")
        
        # Check for stop request
        if stop_check and stop_check():
            self.logger.warning(f"[S5_TWO_STAGE] STOP REQUESTED - Paper: {paper_id}, Stage 1")
            raise InterruptedError("Stop requested during S5_TWO_STAGE")
        
        # Stage 1
        stage1 = self._call_agent(
            fast_model, 
            paper["title"], 
            paper["abstract"],
            paper_id=paper_id,
            paper_index=paper_index,
            lazy_load=lazy_load,
            **kwargs
        )
        all_responses = [stage1]
        total_time = stage1["inference_time"]
        
        if stage1["decision"] == "EXCLUDE" and stage1["confidence"] == "HIGH":
            return {
                "strategy": "S5_TWO_STAGE",
                "final_decision": "EXCLUDE",
                "final_confidence": "HIGH",
                "agent_responses": all_responses,
                "aggregation": {
                    "stage": 1, 
                    "fast_filter": True,
                    "model_roles": {"fast_filter": fast_model, "debate": other_models},
                },
                "total_time": total_time,
            }
        
        # Stage 2
        for i, model_key in enumerate(other_models, 1):
            # Check for stop request
            if stop_check and stop_check():
                self.logger.warning(f"[S5_TWO_STAGE] STOP REQUESTED - Paper: {paper_id}, Stage 2, Agent {i}/{len(other_models)}")
                raise InterruptedError("Stop requested during S5_TWO_STAGE stage 2")
            
            # Check memory
            try:
                check_memory_limit(self.logger, f"S5 stage 2 before agent {i}/{len(other_models)}")
            except MemoryError:
                self.logger.error(f"[S5_TWO_STAGE] Memory limit reached, stopping")
                raise
            
            response = self._call_agent(
                model_key, 
                paper["title"], 
                paper["abstract"],
                paper_id=paper_id,
                paper_index=paper_index,
                lazy_load=lazy_load,
                **kwargs
            )
            all_responses.append(response)
            total_time += response["inference_time"]
            
            # Cleanup between agents
            if i < len(other_models):
                time.sleep(0.5)
                gc.collect()
        
        # Determine final decision
        decisions = [r["decision"] for r in all_responses]
        if len(set(decisions)) == 1:
            final_decision = decisions[0]
            final_confidence = "HIGH"
        else:
            votes = {"INCLUDE": decisions.count("INCLUDE"), "EXCLUDE": decisions.count("EXCLUDE")}
            final_decision = "INCLUDE" if votes["INCLUDE"] >= votes["EXCLUDE"] else "EXCLUDE"
            final_confidence = "MEDIUM"
        
        return {
            "strategy": "S5_TWO_STAGE",
            "final_decision": final_decision,
            "final_confidence": final_confidence,
            "agent_responses": all_responses,
            "aggregation": {
                "stage": 2, 
                "consensus": len(set(decisions)) == 1,
                "model_roles": {"fast_filter": fast_model, "debate": other_models},
            },
            "total_time": total_time,
        }

class ErrorAnalysisRequest(BaseModel):
    """Request model for detailed error analysis."""
    project_id: str
    strategy: Optional[str] = None
    model: Optional[str] = None
    prompt_mode: Optional[str] = None
    uncertain_treatment: str = "INCLUDE"
    job_id: Optional[str] = None

# =============================================================================
# JOB MANAGER
# =============================================================================

# =============================================================================
# LLM DECISIONS MONGODB STORAGE (Phase 6)
# =============================================================================

LLM_DECISIONS_COLLECTION = "llm_decisions"

def save_llm_decision_to_mongodb(db, result: Dict, job) -> Optional[str]:
    """
    Save LLM screening decision to MongoDB.
    
    Args:
        db: MongoDB database connection
        result: Screening result dictionary
        job: Current screening job (ScreeningJob instance)
    
    Returns:
        Inserted/updated document ID or None on error
    """
    func_logger = logging.getLogger("LLMDecisions")
    
    try:
        # Extract model(s) from result or job
        # For multi-agent strategies (S2-S5), extract all models from agent_responses
        model = result.get("model")
        if not model:
            if result.get("agent_responses"):
                # Get unique models from all agent responses
                models_used = []
                for r in result["agent_responses"]:
                    m = r.get("model")
                    if m and m not in models_used:
                        models_used.append(m)
                model = ",".join(models_used) if models_used else (job.models[0] if job.models else "unknown")
            elif job.models:
                model = ",".join(job.models) if len(job.models) > 1 else job.models[0]
            else:
                model = "unknown"

        # Extract reasoning from first agent response if not at top level
        reasoning = result.get("reasoning", "")
        if not reasoning and result.get("agent_responses"):
            first_response = result["agent_responses"][0]
            reasoning = first_response.get("reasoning", "")
        
        # Extract criteria from first agent response if not at top level
        criteria_met = result.get("criteria_met", [])
        criteria_violated = result.get("criteria_violated", [])
        if not criteria_met and not criteria_violated and result.get("agent_responses"):
            first_response = result["agent_responses"][0]
            criteria_met = first_response.get("criteria_met", [])
            criteria_violated = first_response.get("criteria_violated", [])
        
        # Convert confidence string to numeric score (0-1)
        final_confidence = result.get("final_confidence") or result.get("confidence", "LOW")
        confidence_map = {"HIGH": 0.9, "MEDIUM": 0.7, "LOW": 0.5}
        confidence_score = confidence_map.get(final_confidence.upper(), 0.5)
        
        # Prepare document
        doc = {
            "project_id": job.project_id,
            "gs_id": result.get("paper_id"),
            "paper_id": result.get("paper_id"),  # Alias for frontend compatibility
            "title": result.get("title", ""),
            "job_id": job.job_id,
            "strategy": result.get("strategy"),
            "model": model,
            "prompt_mode": job.prompt_mode,
            "final_decision": result.get("final_decision") or result.get("decision"),
            "final_confidence": final_confidence,
            "confidence_score": confidence_score,  # NEW: Numeric confidence for frontend
            "criteria_met": criteria_met,
            "criteria_violated": criteria_violated,
            "reasoning": reasoning,
            "agent_responses": result.get("agent_responses", []),
            "total_time": result.get("total_time"),
            "aggregation": result.get("aggregation"),  # S5 stage/role data
            "timestamp": datetime.utcnow(),
            "data_source": job.data_source,
            "antelope_account": job.antelope_account,  # NEW: Track user
        }
        
        # Log to blockchain (per-paper transaction)
        if job.antelope_account and BLOCKCHAIN_ENABLED and BLOCKCHAIN_AVAILABLE:
            try:
                # Prepare decision data for blockchain
                decision = doc["final_decision"]
                # Map decision to blockchain format
                if decision in ["INCLUDE", "EXCLUDE", "UNCERTAIN"]:
                    bc_decision = decision
                else:
                    bc_decision = "UNCERTAIN"
                
                # Create data hash for verification
                decision_str = json.dumps({
                    "paper_id": doc["paper_id"],
                    "decision": bc_decision,
                    "confidence": final_confidence,
                    "strategy": doc["strategy"],
                    "model": model
                }, sort_keys=True)
                data_hash = hashlib.sha256(decision_str.encode()).hexdigest()[:64]
                
                blockchain_data = {
                    "screener": job.antelope_account,
                    "projectid": job.project_id,
                    "gsid": result.get("paper_id", "unknown"),
                    "decision": bc_decision,
                    "confidence": final_confidence.upper(),
                    "model": model,
                    "strategy": doc["strategy"],
                    "jobid": job.job_id,
                    "datahash": data_hash
                }
                
                tx_id = log_paper_decision_to_blockchain(blockchain_data)
                if tx_id:
                    doc["transaction_id"] = tx_id
                    print(f"✓ Paper decision logged to blockchain: {result.get('paper_id')} -> {tx_id[:16]}...")
            except Exception as e:
                func_logger.warning(f"Failed to log paper decision to blockchain: {e}")
        
        # Upsert: unique key = project_id + gs_id + strategy + model + prompt_mode
        filter_key = {
            "project_id": job.project_id,
            "gs_id": result.get("paper_id"),
            "strategy": result.get("strategy"),
            "model": model,
            "prompt_mode": job.prompt_mode,
        }
        
        update_result = db[LLM_DECISIONS_COLLECTION].update_one(
            filter_key,
            {"$set": doc, "$setOnInsert": {"created_at": datetime.utcnow()}},
            upsert=True
        )
        
        if update_result.upserted_id:
            func_logger.debug(f"Inserted LLM decision for {result.get('paper_id')}")
        else:
            func_logger.debug(f"Updated LLM decision for {result.get('paper_id')}")
        
        return str(update_result.upserted_id) if update_result.upserted_id else "updated"
            
    except Exception as e:
        func_logger.error(f"Failed to save LLM decision: {e}")
        return None

def save_job_to_mongodb(db, job) -> bool:
    """
    Save or update job metadata to MongoDB llm_jobs collection.
    
    Args:
        db: MongoDB database connection
        job: ScreeningJob instance
    
    Returns:
        True if successful, False otherwise
    """
    func_logger = logging.getLogger("LLMJobs")
    
    try:
        from dataclasses import asdict
        job_data = asdict(job)
        # Remove created_at from job_data to avoid conflict with $setOnInsert
        job_data.pop("created_at", None)
        job_data["updated_at"] = datetime.utcnow()
        
        # Upsert based on job_id
        db["llm_jobs"].update_one(
            {"job_id": job.job_id},
            {"$set": job_data, "$setOnInsert": {"created_at": datetime.utcnow()}},
            upsert=True
        )
        func_logger.debug(f"Saved job {job.job_id} to MongoDB")
        return True
    except Exception as e:
        func_logger.error(f"Failed to save job to MongoDB: {e}")
        return False

# =============================================================================
# SCREENING JOB
# =============================================================================

@dataclass
class ScreeningJob:
    job_id: str
    project_id: str
    data_source: str
    strategies: List[str]
    models: List[str]
    prompt_mode: str
    output_filename: str
    status: str = "pending"
    total_papers: int = 0
    processed_papers: int = 0
    current_paper: str = ""
    current_strategy: str = ""
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    error: Optional[str] = None
    results_file: Optional[str] = None
    evaluation_only: bool = True      # NEW
    save_to_mongodb: bool = True      # NEW
    antelope_account: Optional[str] = None  # NEW: User who initiated screening
    transaction_id: Optional[str] = None  # NEW: Blockchain transaction ID
    resume_job_id: Optional[str] = None  # NEW: Job ID being resumed (if any)
    s5_model_roles: Optional[Dict[str, Any]] = None

class JobManager:
    """Manages screening jobs."""
    
    def __init__(self, model_manager: MLXModelManager, db):
        self.model_manager = model_manager
        self.db = db
        self.engine = ScreeningEngine(model_manager)
        self.jobs: Dict[str, ScreeningJob] = {}
        self.active_job: Optional[str] = None
        self.stop_requested: bool = False
        self.websocket_connections: List[WebSocket] = []
        self.last_connection_time: Optional[float] = None  # Track when last WS connected
        self.connection_timeout: float = 10.0  # Auto-pause after 10 seconds without connections
        self.logger = logging.getLogger("JobManager")
    
    def check_connection_timeout(self):
        """Check if job should be paused due to no active connections."""
        if not self.active_job:
            return False
        
        # If there are active connections, update timestamp and continue
        if len(self.websocket_connections) > 0:
            self.last_connection_time = time.time()
            return False
        
        # No connections - check timeout
        if self.last_connection_time is None:
            self.last_connection_time = time.time()
            return False
        
        elapsed = time.time() - self.last_connection_time
        if elapsed > self.connection_timeout:
            self.logger.warning(f"⚠️  No WebSocket connections for {elapsed:.1f}s - AUTO-PAUSING job {self.active_job}")
            self.stop_requested = True
            return True
        
        return False
    
    async def broadcast(self, message: Dict):
        """Broadcast message to all WebSocket connections."""
        dead_connections = []
        # Iterate over a copy to avoid 'list modified during iteration' error
        for ws in self.websocket_connections.copy():
            try:
                await ws.send_json(message)
            except Exception as e:
                self.logger.debug(f"WebSocket send failed: {e}")
                dead_connections.append(ws)
        # Remove dead connections
        for ws in dead_connections:
            if ws in self.websocket_connections:
                self.websocket_connections.remove(ws)
        
        # Update connection tracking
        if len(self.websocket_connections) > 0:
            self.last_connection_time = time.time()
    
    def create_job(self, request: StartScreeningRequest) -> ScreeningJob:
        """Create a new screening job or resume an existing one."""
        
        # If resuming, use the original job_id
        if request.resume_job_id:
            job_id = request.resume_job_id
            self.logger.info(f"[CREATE_JOB] 🔄 RESUMING existing job: {job_id}")
            
            # Try to load existing job from MongoDB
            if self.db is not None:
                existing_job = self.db["llm_jobs"].find_one({"job_id": job_id})
                if existing_job:
                    self.logger.info(f"[CREATE_JOB] Found existing job in MongoDB with status: {existing_job.get('status')}")
                    # Reuse existing output filename and timestamp
                    output_filename = existing_job.get("output_filename", f"screening_{request.project_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl")
                else:
                    self.logger.warning(f"[CREATE_JOB] Job {job_id} not found in MongoDB, creating new record")
                    output_filename = request.output_filename or f"screening_{request.project_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
            else:
                output_filename = request.output_filename or f"screening_{request.project_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
        else:
            # Create new job with new ID
            job_id = str(uuid.uuid4())[:8]
            self.logger.info(f"[CREATE_JOB] ✨ Creating NEW job: {job_id}")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_filename = request.output_filename or f"screening_{request.project_id}_{timestamp}"
        
        if not output_filename.endswith(".jsonl"):
            output_filename += ".jsonl"
        
        job = ScreeningJob(
            job_id=job_id,
            project_id=request.project_id,
            data_source=request.data_source.value,
            strategies=[s.value for s in request.strategies],
            models=request.models,
            prompt_mode=request.prompt_mode.value,
            output_filename=output_filename,
            evaluation_only=request.evaluation_only,      # NEW
            save_to_mongodb=request.save_to_mongodb,      # NEW
            antelope_account=request.antelope_account,    # NEW
            resume_job_id=request.resume_job_id,          # NEW (but will be same as job_id if resuming)
            s5_model_roles=request.s5_model_roles,
        )
        
        self.jobs[job_id] = job
        
        # Save job to MongoDB
        if self.db is not None:
            save_job_to_mongodb(self.db, job)
        
        return job
    
    async def run_job(self, job_id: str, few_shot_examples: List[Dict] = None):
        """Run a screening job with detailed logging."""
        job = self.jobs.get(job_id)
        if not job:
            self.logger.error(f"[RUN_JOB] Job {job_id} not found")
            return
        
        self.logger.info(f"="*80)
        self.logger.info(f"[RUN_JOB] STARTING JOB: {job_id}")
        self.logger.info(f"[RUN_JOB] Project: {job.project_id}")
        self.logger.info(f"[RUN_JOB] Data Source: {job.data_source}")
        self.logger.info(f"[RUN_JOB] Strategies: {job.strategies}")
        self.logger.info(f"[RUN_JOB] Models: {job.models}")
        self.logger.info(f"="*80)
        
        # CRITICAL: In memory-efficient mode, unload all models before starting
        # This ensures fresh start and prevents GPU memory issues
        if self.model_manager.memory_efficient_mode:
            self.logger.info("[RUN_JOB] Memory-efficient mode: Unloading all pre-loaded models...")
            loaded_models = self.model_manager.get_loaded_models()
            for model_key in loaded_models:
                self.logger.info(f"[RUN_JOB] Unloading {model_key}...")
                self.model_manager.unload_model(model_key)
            gc.collect()
            self.logger.info("[RUN_JOB] All models unloaded - ready for lazy loading")
        
        self.active_job = job_id
        self.stop_requested = False
        self.last_connection_time = time.time()  # Reset connection timer
        
        job.status = "running"
        job.start_time = datetime.now().isoformat()
        
        # Update job in MongoDB
        if self.db is not None:
            save_job_to_mongodb(self.db, job)
        
        log_resource_usage(self.logger, "Job start")
        
        await self.broadcast({"type": "job_started", "job_id": job_id})
        
        try:
            # Get papers from database
            if job.data_source == "corpus":
                collection = self.db["corpus_papers"]
                query = {"project_id": job.project_id}
            else:
                collection = self.db["gold_standard"]
                # Filter: exclude calibration papers if evaluation_only=True
                if job.evaluation_only:
                    query = {"project_id": job.project_id, "is_calibration": {"$ne": True}}
                    self.logger.info(f"[RUN_JOB] Filtering: Evaluation papers only (excluding calibration)")
                else:
                    query = {"project_id": job.project_id}
                    self.logger.info(f"[RUN_JOB] Including ALL gold standard papers")
            
            # CRITICAL FIX: Add consistent sort order to ensure papers are always loaded in the same sequence
            # This is essential for resume functionality across different machines
            # Sort by _id to guarantee deterministic order (MongoDB ObjectId is unique and sortable)
            papers = list(collection.find(query).sort("_id", 1))
            self.logger.info(f"[RUN_JOB] Loaded {len(papers)} papers with consistent sort order (_id ascending)")
            job.total_papers = len(papers)
            
            await self.broadcast({
                "type": "job_info",
                "job_id": job_id,
                "total_papers": job.total_papers,
                "strategies": job.strategies,
                "models": job.models,
            })
            
            # Prepare output file
            results_path = Path(RESULTS_DIR).expanduser() / job.output_filename
            job.results_file = str(results_path)
            
            # Screening kwargs
            kwargs = {"prompt_mode": PromptMode(job.prompt_mode)}
            if job.prompt_mode == "few_shot": 
                if few_shot_examples and len(few_shot_examples) > 0: # Use provided examples kwargs["few_shot_examples"] = few_shot_examples self.logger.info(f"[RUN_JOB] Using {len(few_shot_examples)} provided few-shot examples") else: # Load from database (calibration set) self.logger.info(f"[RUN_JOB] Few-shot mode: Loading examples from calibration set...") db_examples = get_fewshot_examples_from_db(job.project_id, self.db) if db_examples: kwargs["few_shot_examples"] = db_examples self.logger.info(f"[RUN_JOB] Loaded {len(db_examples)} few-shot examples from database") else: self.logger.error(f"[RUN_JOB] No few-shot examples available - calibration screening not complete") job.status = "failed" job.error = "No few-shot examples available. Complete calibration screening first." await self.broadcast({"type": "job_failed", "job_id": job_id, "error": job.error}) return             
                    kwargs["few_shot_examples"] = few_shot_examples
                    self.logger.info(f"[RUN_JOB] Using {len(few_shot_examples)} provided few-shot examples")
                else: # Load from database (calibration set)
                    self.logger.info(f"[RUN_JOB] Few-shot mode: Loading examples from calibration set...")
                    db_examples = get_fewshot_examples_from_db(job.project_id, self.db)
                    if db_examples:
                        kwargs["few_shot_examples"] = db_examples
                        self.logger.info(f"[RUN_JOB] Loaded {len(db_examples)} few-shot examples from database")
                    else:
                        self.logger.error(f"[RUN_JOB] No few-shot examples available - calibration screening not complete")
                        job.status = "failed"
                        job.error = "No few-shot examples available. Complete calibration screening first."
                        
                        # Update job in MongoDB
                        if self.db is not None:
                            save_job_to_mongodb(self.db, job)
                        
                        await self.broadcast({"type": "job_failed", "job_id": job_id, "error": job.error})
                        return             
            
            # RESUME CAPABILITY: Check for already-completed papers
            already_completed = 0
            if job.resume_job_id and job.save_to_mongodb and self.db is not None:
                self.logger.info(f"[RUN_JOB] 🔄 RESUME MODE: Checking progress for job {job_id}")
                # Count UNIQUE papers (not decisions) that have been completed FOR THIS SPECIFIC JOB
                # Filter ONLY by job_id (which is unique) to avoid confusion with other jobs
                pipeline = [
                    {"$match": {"job_id": job_id}},
                    {"$group": {"_id": "$gs_id"}},
                    {"$count": "unique_papers"}
                ]
                unique_result = list(self.db[LLM_DECISIONS_COLLECTION].aggregate(pipeline))
                already_completed = unique_result[0]["unique_papers"] if unique_result else 0
                
                if already_completed > 0:
                    self.logger.info(f"[RUN_JOB] Found {already_completed} unique papers already completed in job {job_id}")
                    self.logger.info(f"[RUN_JOB] Will skip already-processed papers and continue from where left off")
                else:
                    self.logger.info(f"[RUN_JOB] No prior progress found for job {job_id} - starting fresh")
            elif not job.resume_job_id:
                self.logger.info(f"[RUN_JOB] Starting NEW screening (no resume - will process all papers)")
            
            # Track actual paper number (accounts for already processed papers)
            papers_processed_before_resume = already_completed if (job.resume_job_id and already_completed > 0) else 0
            
            with open(results_path, "w") as f:
                papers_processed_this_session = 0
                papers_skipped = 0
                
                for i, paper in enumerate(papers):
                    # Simple sequential paper number (1-based)
                    paper_number = i + 1
                    
                    # Check for stop request or connection timeout
                    if self.stop_requested:
                        self.logger.warning(f"[RUN_JOB] STOP REQUESTED - Cancelling at paper {paper_number}/{job.total_papers}")
                        job.status = "cancelled"
                        break
                    
                    # Auto-pause if no WebSocket connections (browser crash/refresh)
                    if self.check_connection_timeout():
                        self.logger.warning(f"[RUN_JOB] No active connections - PAUSING at paper {paper_number}/{job.total_papers}")
                        job.status = "paused"
                        break
                    
                    paper_id = paper.get("corpus_id") or paper.get("gs_id") or str(paper["_id"])
                    job.current_paper = paper_id
                    job.processed_papers = papers_processed_before_resume + papers_processed_this_session
                    
                    # RESUME CAPABILITY: Check if this entire paper is already completed (all strategies done)
                    # Filter by job_id + gs_id + strategy only (no model filter) because
                    # multi-model strategies like S5 save model as a comma-joined string
                    # (e.g. "modelA,modelB,modelC") which won't match individual model keys.
                    paper_fully_completed = False
                    if job.resume_job_id and job.save_to_mongodb and self.db is not None:
                        # Check if all strategies have at least one decision for this paper IN THIS JOB
                        all_completed = True
                        for strategy in job.strategies:
                            existing = self.db[LLM_DECISIONS_COLLECTION].count_documents({
                                "job_id": job_id,  # ONLY check this specific job
                                "gs_id": paper_id,
                                "strategy": strategy,
                            })
                            if existing == 0:
                                all_completed = False
                                break
                        
                        if all_completed:
                            self.logger.info(f"[RUN_JOB] ⏭️  SKIPPING paper {paper_number}/{job.total_papers}: {paper_id} (already completed in job {job_id})")
                            paper_fully_completed = True
                            papers_skipped += 1
                    
                    if paper_fully_completed:
                        continue
                    
                    papers_processed_this_session += 1
                    
                    self.logger.info(f"\n{'='*60}")
                    self.logger.info(f"[RUN_JOB] Processing paper {paper_number}/{job.total_papers}: {paper_id} (#{papers_processed_this_session} this session, {papers_skipped} skipped)")
                    self.logger.info(f"[RUN_JOB] Title: {paper.get('title', '')[:100]}...")
                    log_resource_usage(self.logger, f"Before paper {paper_number}")
                    
                    paper_data = {
                        "title": paper.get("title", ""),
                        "abstract": paper.get("abstract", ""),
                    }
                    
                    # Stop check function for strategies
                    def check_stop():
                        return self.stop_requested
                    
                    for strategy in job.strategies:
                        if self.stop_requested:
                            self.logger.warning(f"[RUN_JOB] STOP REQUESTED - Cancelling strategy {strategy}")
                            job.status = "cancelled"
                            break
                        
                        job.current_strategy = strategy
                        
                        # RESUME CAPABILITY: Check if this paper+strategy already processed IN THIS JOB
                        # No model filter - multi-model strategies (S5) save model as comma-joined string
                        skip_strategy = False
                        if job.resume_job_id and job.save_to_mongodb and self.db is not None:
                            existing = self.db[LLM_DECISIONS_COLLECTION].find_one({
                                "job_id": job_id,  # ONLY check this specific job
                                "gs_id": paper_id,
                                "strategy": strategy,
                            })
                            if existing:
                                self.logger.info(f"[RUN_JOB] ⏭️  SKIPPING {strategy} for {paper_id} (already completed in job {job_id})")
                                skip_strategy = True
                        
                        if skip_strategy:
                            continue
                        
                        self.logger.info(f"[RUN_JOB] Starting strategy: {strategy}")
                        
                        # Calculate current position: already completed + currently processing
                        current_paper_index = papers_processed_before_resume + papers_processed_this_session
                        
                        await self.broadcast({
                            "type": "progress",
                            "job_id": job_id,
                            "paper_index": current_paper_index,
                            "papers_this_session": papers_processed_this_session,
                            "paper_id": paper_id,
                            "strategy": strategy,
                            "total": job.total_papers,
                            "percent": round(100 * current_paper_index / job.total_papers, 1),
                        })
                        
                        # Execute strategy with error handling
                        try:
                            strategy_start = time.time()
                            
                            # Add paper context to kwargs
                            kwargs['paper_id'] = paper_id
                            kwargs['paper_index'] = current_paper_index
                            
                            if strategy == "S1_SINGLE":
                                for model_key in job.models:
                                    if self.stop_requested:
                                        self.logger.warning(f"[RUN_JOB] STOP REQUESTED during S1")
                                        raise InterruptedError("Stop requested")
                                    
                                    result = self.engine.screen_single(
                                        paper_data, model_key, stop_check=check_stop, **kwargs
                                    )
                                    result["paper_id"] = paper_id
                                    result["title"] = paper.get("title", "")
                                    result["model"] = model_key
                                    result["strategy"] = strategy
                                    result["timestamp"] = datetime.now().isoformat()
                                    f.write(json.dumps(result) + "\n")
                                    
                                    # Save to MongoDB if enabled
                                    if job.save_to_mongodb:
                                        save_llm_decision_to_mongodb(self.db, result, job)
                                    
                            elif strategy == "S2_MAJORITY":
                                result = self.engine.screen_majority(
                                    paper_data, job.models, stop_check=check_stop, **kwargs
                                )
                                result["paper_id"] = paper_id
                                result["title"] = paper.get("title", "")
                                result["timestamp"] = datetime.now().isoformat()
                                f.write(json.dumps(result) + "\n")
                                
                                # Save to MongoDB if enabled
                                if job.save_to_mongodb:
                                    save_llm_decision_to_mongodb(self.db, result, job)

                            elif strategy == "S3_RECALL_OPT":
                                result = self.engine.screen_recall_optimized(
                                    paper_data, job.models, stop_check=check_stop, **kwargs
                                )
                                result["paper_id"] = paper_id
                                result["title"] = paper.get("title", "")
                                result["timestamp"] = datetime.now().isoformat()
                                f.write(json.dumps(result) + "\n")
                                
                                # Save to MongoDB if enabled
                                if job.save_to_mongodb:
                                    save_llm_decision_to_mongodb(self.db, result, job)

                            elif strategy == "S4_CONFIDENCE":
                                result = self.engine.screen_confidence_weighted(
                                    paper_data, job.models, stop_check=check_stop, **kwargs
                                )
                                result["paper_id"] = paper_id
                                result["title"] = paper.get("title", "")
                                result["timestamp"] = datetime.now().isoformat()
                                f.write(json.dumps(result) + "\n")
                                
                                # Save to MongoDB if enabled
                                if job.save_to_mongodb:
                                    save_llm_decision_to_mongodb(self.db, result, job)

                            elif strategy == "S5_TWO_STAGE":
                                result = self.engine.screen_two_stage(
                                    paper_data, job.models, stop_check=check_stop,
                                    s5_model_roles=job.s5_model_roles,
                                    **kwargs
                                )                                
                                result["paper_id"] = paper_id
                                result["title"] = paper.get("title", "")
                                result["timestamp"] = datetime.now().isoformat()
                                f.write(json.dumps(result) + "\n")
                                
                                # Save to MongoDB if enabled
                                if job.save_to_mongodb:
                                    save_llm_decision_to_mongodb(self.db, result, job)
                            
                            strategy_time = time.time() - strategy_start
                            self.logger.info(f"[RUN_JOB] Strategy {strategy} completed in {strategy_time:.2f}s")
                            
                            f.flush()
                            
                        except InterruptedError as ie:
                            self.logger.warning(f"[RUN_JOB] Job interrupted: {ie}")
                            job.status = "cancelled"
                            raise
                            
                        except Exception as e:
                            error_trace = traceback.format_exc()
                            self.logger.error(f"[RUN_JOB] Strategy {strategy} FAILED for paper {paper_id}")
                            self.logger.error(f"[RUN_JOB] Error: {str(e)}")
                            self.logger.error(f"[RUN_JOB] Traceback:\n{error_trace}")
                            
                            # Write error result
                            error_result = {
                                "paper_id": paper_id,
                                "strategy": strategy,
                                "status": "error",
                                "error": str(e),
                                "error_traceback": error_trace,
                                "timestamp": datetime.now().isoformat(),
                            }
                            f.write(json.dumps(error_result) + "\n")
                            f.flush()
                            
                            # For S2, this is critical - stop the job
                            if strategy == "S2_MAJORITY":
                                self.logger.error(f"[RUN_JOB] S2_MAJORITY failed - stopping job")
                                job.status = "failed"
                                job.error = f"S2_MAJORITY failed at paper {i+1}: {str(e)}"
                                
                                # Update job in MongoDB
                                if self.db is not None:
                                    save_job_to_mongodb(self.db, job)
                                
                                raise
                    
                    # Memory check and cleanup after each paper
                    try:
                        mem_after_paper = check_memory_limit(self.logger, f"After paper {i+1}/{job.total_papers}")
                    except MemoryError as me:
                        self.logger.error(f"[RUN_JOB] Memory limit exceeded after paper {i+1}")
                        job.status = "failed"
                        job.error = str(me)
                        
                        # Update job in MongoDB
                        if self.db is not None:
                            save_job_to_mongodb(self.db, job)
                        
                        raise
                    
                    # Force garbage collection between papers
                    gc.collect()
                    
                    # Allow other async tasks
                    await asyncio.sleep(0.1)  # Slightly longer delay for cleanup
            
            if job.status not in ["cancelled", "failed", "paused"]:
                job.status = "completed"
                
                # Log completed job to blockchain
                print(f"\n{'='*80}")
                print(f"[BLOCKCHAIN CHECK] Starting blockchain logging...")
                print(f"[BLOCKCHAIN CHECK] antelope_account: {job.antelope_account}")
                print(f"[BLOCKCHAIN CHECK] BLOCKCHAIN_ENABLED: {BLOCKCHAIN_ENABLED}")
                print(f"[BLOCKCHAIN CHECK] BLOCKCHAIN_AVAILABLE: {BLOCKCHAIN_AVAILABLE}")
                print(f"{'='*80}\n")
                
                if job.antelope_account and BLOCKCHAIN_ENABLED:
                    try:
                        # For S5 strategy with role assignment, put fast filter first
                        models_list = job.models
                        if "S5_TWO_STAGE" in job.strategies and job.s5_model_roles:
                            fast_filter = job.s5_model_roles.get("fast_filter")
                            if fast_filter and fast_filter in models_list:
                                # Reorder: fast filter first, then others
                                other_models = [m for m in models_list if m != fast_filter]
                                models_list = [fast_filter] + other_models
                        
                        blockchain_data = {
                            "username": job.antelope_account,
                            "project_id": job.project_id,
                            "job_id": job.job_id,
                            "strategy": ",".join(job.strategies) if job.strategies else "unknown",
                            "models": ",".join(models_list) if models_list else "unknown",
                            "prompt_mode": job.prompt_mode or "unknown",
                            "papers_count": job.total_papers,
                        }
                        print(f"[BLOCKCHAIN] Logging data: {blockchain_data}")
                        transaction_id = log_llm_job_to_blockchain(blockchain_data)
                        if transaction_id:
                            job.transaction_id = transaction_id
                            print(f"✅ [BLOCKCHAIN SUCCESS] Transaction ID: {transaction_id}")
                            self.logger.info(f"[BLOCKCHAIN] Job logged with transaction ID: {transaction_id}")
                        else:
                            print(f"⚠️ [BLOCKCHAIN WARNING] No transaction ID returned")
                    except Exception as e:
                        print(f"❌ [BLOCKCHAIN ERROR] Failed to log job: {e}")
                        self.logger.warning(f"[BLOCKCHAIN] Failed to log job: {e}")
                        import traceback
                        traceback.print_exc()
                else:
                    if not job.antelope_account:
                        print(f"⚠️ [BLOCKCHAIN SKIP] No antelope_account provided")
                    if not BLOCKCHAIN_ENABLED:
                        print(f"⚠️ [BLOCKCHAIN SKIP] Blockchain logging is disabled")
            
            # Calculate total papers processed (before resume + this session)
            total_processed = papers_processed_before_resume + papers_processed_this_session
            # FIXED: Always use actual processed count, not total_papers
            # This ensures accuracy when jobs fail/crash or when papers are skipped in resume mode
            job.processed_papers = total_processed
            job.end_time = datetime.now().isoformat()
            
            # Update job in MongoDB
            if self.db is not None:
                save_job_to_mongodb(self.db, job)
            
            duration = (datetime.fromisoformat(job.end_time) - datetime.fromisoformat(job.start_time)).total_seconds()
            
            self.logger.info(f"\n{'='*80}")
            self.logger.info(f"[RUN_JOB] JOB {job.status.upper()}: {job_id}")
            self.logger.info(f"[RUN_JOB] Processed: {job.processed_papers}/{job.total_papers} papers")
            self.logger.info(f"[RUN_JOB] Duration: {duration:.1f}s")
            self.logger.info(f"[RUN_JOB] Results: {job.results_file}")
            log_resource_usage(self.logger, "Job end")
            self.logger.info(f"{'='*80}\n")
            
            # Broadcast appropriate message based on status
            if job.status == "cancelled":
                await self.broadcast({
                    "type": "job_cancelled",
                    "job_id": job_id,
                    "total_processed": job.processed_papers,
                    "duration_seconds": duration,
                })
            elif job.status == "paused":
                await self.broadcast({
                    "type": "job_paused",
                    "job_id": job_id,
                    "total_processed": job.processed_papers,
                    "duration_seconds": duration,
                    "message": "Job paused due to lost connection. Can be resumed.",
                })
            else:
                await self.broadcast({
                    "type": "job_completed",
                    "job_id": job_id,
                    "status": job.status,
                    "results_file": job.output_filename,
                    "total_processed": job.processed_papers,
                    "duration_seconds": duration,
                })
            
        except InterruptedError:
            # Already handled above
            pass
            
        except Exception as e:
            error_trace = traceback.format_exc()
            job.status = "failed"
            job.error = str(e)
            job.end_time = datetime.now().isoformat()
            
            # Update job in MongoDB
            if self.db is not None:
                save_job_to_mongodb(self.db, job)
            
            self.logger.error(f"\n{'='*80}")
            self.logger.error(f"[RUN_JOB] JOB FAILED: {job_id}")
            self.logger.error(f"[RUN_JOB] Error: {str(e)}")
            self.logger.error(f"[RUN_JOB] Traceback:\n{error_trace}")
            self.logger.error(f"{'='*80}\n")
            
            # Broadcast failure - use simple loop to avoid nested broadcast errors
            dead_connections = []
            for ws in self.websocket_connections.copy():
                try:
                    await ws.send_json({
                        "type": "job_failed",
                        "job_id": job_id,
                        "error": str(e),
                        "traceback": error_trace,
                    })
                except Exception as ws_error:
                    self.logger.debug(f"WebSocket send failed during error broadcast: {ws_error}")
                    dead_connections.append(ws)
            # Remove dead connections
            for ws in dead_connections:
                if ws in self.websocket_connections:
                    self.websocket_connections.remove(ws)
        
        finally:
            # Clear active job only after everything is done
            if self.active_job == job_id:
                self.active_job = None
                self.logger.debug(f"[RUN_JOB] Cleared active_job: {job_id}")
    
    def stop_job(self, job_id: str) -> bool:
        """Request job stop."""
        job = self.jobs.get(job_id)
        if not job:
            self.logger.warning(f"[STOP_JOB] Job {job_id} not found in jobs dict")
            return False
        
        # Can stop if it's the active job or if it's in a running/processing state
        if self.active_job == job_id:
            self.logger.info(f"[STOP_JOB] Stop requested for active job: {job_id}")
            self.stop_requested = True
            return True
        
        # If job exists but is not active, check if it's in a stoppable state
        if job.status in ["running", "pending"]:
            self.logger.warning(f"[STOP_JOB] Job {job_id} exists but is not active, marking as cancelled")
            job.status = "cancelled"
            job.end_time = datetime.now().isoformat()
            return True
        
        # If job already completed/failed/cancelled, acknowledge the stop request
        if job.status in ["completed", "failed", "cancelled"]:
            self.logger.info(f"[STOP_JOB] Job {job_id} already {job.status}, acknowledging stop request")
            return True
        
        self.logger.warning(f"[STOP_JOB] Cannot stop job {job_id} with status {job.status}")
        return False

# =============================================================================
# APPLICATION
# =============================================================================

app = FastAPI(
    title="PaSSER-SR LLM Screening API",
    description="LLM-based screening service with WebSocket progress updates",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Custom validation error handler for debugging
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Log detailed validation errors for debugging."""
    body = await request.body()
    logger.error(f"Validation error for {request.method} {request.url.path}")
    logger.error(f"Request body: {body.decode('utf-8')}")
    logger.error(f"Validation errors: {exc.errors()}")
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "body": body.decode('utf-8')}
    )

# Global state
model_manager = MLXModelManager()
db = None
job_manager = None

# =============================================================================
# STARTUP
# =============================================================================

@app.on_event("startup")
async def startup():
    global db, job_manager
    
    # Setup logging
    log_file = setup_logging()
    logger = logging.getLogger("startup")
    logger.info(f"Log file: {log_file}")
    
    try:
        client = MongoClient(DEFAULT_MONGO_URI, serverSelectionTimeoutMS=5000)
        client.admin.command('ping')
        db = client[DEFAULT_DB_NAME]
        logger.info(f"✓ Connected to MongoDB: {DEFAULT_DB_NAME}")
        print(f"✓ Connected to MongoDB: {DEFAULT_DB_NAME}")

                # Create indexes for llm_decisions collection
        try:
            db[LLM_DECISIONS_COLLECTION].create_index([
                ("project_id", 1),
                ("gs_id", 1),
                ("strategy", 1),
                ("model", 1),
                ("prompt_mode", 1)
            ], unique=True, name="unique_decision_idx")
            db[LLM_DECISIONS_COLLECTION].create_index("project_id", name="project_idx")
            db[LLM_DECISIONS_COLLECTION].create_index("gs_id", name="gs_idx")
            logger.info(f"✓ Created indexes for {LLM_DECISIONS_COLLECTION}")
            
            # Create indexes for llm_jobs collection
            db["llm_jobs"].create_index("job_id", unique=True, name="job_id_idx")
            db["llm_jobs"].create_index("project_id", name="project_id_idx")
            db["llm_jobs"].create_index("status", name="status_idx")
            db["llm_jobs"].create_index("transaction_id", name="transaction_id_idx")
            logger.info("✓ Created indexes for llm_jobs collection")
        except Exception as idx_err:
            logger.warning(f"Index creation warning: {idx_err}")

    except Exception as e:
        logger.error(f"⚠ MongoDB connection failed: {e}")
        print(f"⚠ MongoDB connection failed: {e}")
    
    job_manager = JobManager(model_manager, db)
    logger.info("✓ LLM Screening API ready")
    print(f"✓ LLM Screening API ready")
    print(f"📝 Logs: {log_file}")

# =============================================================================
# REST ENDPOINTS
# =============================================================================

@app.get("/api/llm/status")
async def get_status():
    """Get service status."""
    return {
        "status": "running",
        "mlx_available": MLX_AVAILABLE,
        "loaded_models": model_manager.get_loaded_models(),
        "active_job": job_manager.active_job if job_manager else None,
        "cache_volume": CACHE_VOLUME,
        "results_dir": RESULTS_DIR,
        "memory_efficient_mode": model_manager.memory_efficient_mode if model_manager else True,
        "memory_usage_mb": get_memory_usage(),
    }

@app.get("/api/llm/models")
async def list_models():
    """List available models."""
    models = []
    for key, config in AVAILABLE_MODELS.items():
        models.append({
            "key": key,
            "name": config.name,
            "model_id": config.model_id,
            "description": config.description,
            "loaded": model_manager.is_loaded(key),
        })
    return {"models": models}

@app.post("/api/llm/models/load")
async def load_model(request: LoadModelRequest):
    """Load a model into memory."""
    if not MLX_AVAILABLE:
        raise HTTPException(status_code=503, detail="MLX not available")
    
    try:
        result = model_manager.load_model(request.model_key)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/llm/models/unload")
async def unload_model(request: LoadModelRequest):
    """Unload a model from memory."""
    result = model_manager.unload_model(request.model_key)
    return result

@app.get("/api/llm/strategies")
async def list_strategies():
    """List available strategies."""
    return {
        "strategies": [
            {"key": "S1_SINGLE", "name": "S1: Single-Agent", "description": "One model classifies (baseline)"},
            {"key": "S2_MAJORITY", "name": "S2: Majority Voting", "description": "3 models vote, majority wins"},
            {"key": "S3_RECALL_OPT", "name": "S3: Recall-Optimized", "description": "Any INCLUDE = INCLUDE"},
            {"key": "S4_CONFIDENCE", "name": "S4: Confidence-Weighted", "description": "Weighted by confidence scores"},
            {"key": "S5_TWO_STAGE", "name": "S5: Two-Stage", "description": "Fast filter + debate"},
        ]
    }

@app.get("/api/llm/jobs/resumable")
async def list_resumable_jobs(project_id: Optional[str] = Query(None, description="Filter by project ID")):
    """List jobs that can be resumed (paused, cancelled, failed, or orphaned running jobs)."""
    if db is None:
        return {"resumable_jobs": []}
    
    try:
        # Query for jobs that are not completed
        # Include "running" jobs that are orphaned (no active job in JobManager)
        query = {"status": {"$in": ["paused", "cancelled", "failed", "running"]}}
        if project_id:
            query["project_id"] = project_id
        
        jobs_cursor = db["llm_jobs"].find(query, {"_id": 0}).sort("created_at", -1).limit(50)
        jobs_list = list(jobs_cursor)
        
        # Filter out truly active running jobs (exclude the job currently being processed by JobManager)
        active_job_id = job_manager.active_job if job_manager and hasattr(job_manager, 'active_job') else None
        jobs_list = [j for j in jobs_list if j.get("status") != "running" or j.get("job_id") != active_job_id]
        
        # Enrich with progress information from llm_decisions
        resumable_jobs = []
        for job in jobs_list:
            job_id = job.get("job_id")
            
            # Count completed papers for this job
            completed_count = db[LLM_DECISIONS_COLLECTION].count_documents({"job_id": job_id})
            
            # Get unique papers (a paper might have multiple strategies/models)
            pipeline = [
                {"$match": {"job_id": job_id}},
                {"$group": {"_id": "$gs_id"}},
                {"$count": "unique_papers"}
            ]
            unique_result = list(db[LLM_DECISIONS_COLLECTION].aggregate(pipeline))
            unique_papers = unique_result[0]["unique_papers"] if unique_result else 0
            
            resumable_jobs.append({
                "job_id": job_id,
                "project_id": job.get("project_id"),
                "status": job.get("status"),
                "strategies": job.get("strategies", []),
                "models": job.get("models", []),
                "prompt_mode": job.get("prompt_mode"),
                "data_source": job.get("data_source"),
                "evaluation_only": job.get("evaluation_only", True),
                "total_papers": job.get("total_papers", 0),
                "processed_papers": job.get("processed_papers", 0),
                "unique_papers_completed": unique_papers,
                "decisions_saved": completed_count,
                "start_time": job.get("start_time"),
                "end_time": job.get("end_time"),
                "created_at": job.get("created_at"),
            })
        
        return {
            "project_id": project_id,
            "total_resumable": len(resumable_jobs),
            "resumable_jobs": resumable_jobs
        }
    except Exception as e:
        logging.getLogger("API").error(f"Failed to fetch resumable jobs: {e}")
        return {"resumable_jobs": [], "error": str(e)}

@app.delete("/api/llm/jobs/{job_id}")
async def delete_job(job_id: str, force: bool = Query(False, description="Force delete even if running")):
    """Delete a job and its associated decisions from MongoDB."""
    delete_logger = logging.getLogger("API")
    
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available")
    
    try:
        # Check if job exists
        job = db["llm_jobs"].find_one({"job_id": job_id})
        if not job:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        
        # Don't allow deleting running jobs unless force=True
        if job.get("status") == "running" and not force:
            raise HTTPException(status_code=400, detail="Cannot delete a running job. Use force=true to override or stop it first.")
        
        # If forcing deletion of running job, clear it from active jobs
        if job.get("status") == "running" and force:
            if job_manager.active_job == job_id:
                job_manager.active_job = None
                job_manager.stop_requested = True
                delete_logger.warning(f"[DELETE_JOB] Force-deleting active job {job_id}")
        
        # Delete associated LLM decisions
        decisions_result = db[LLM_DECISIONS_COLLECTION].delete_many({"job_id": job_id})
        
        # Delete the job record
        job_result = db["llm_jobs"].delete_one({"job_id": job_id})
        
        delete_logger.info(f"[DELETE_JOB] Deleted job {job_id}: {job_result.deleted_count} job record, {decisions_result.deleted_count} decisions")
        
        return {
            "success": True,
            "job_id": job_id,
            "deleted_decisions": decisions_result.deleted_count,
            "message": f"Job {job_id} and {decisions_result.deleted_count} decisions deleted successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        delete_logger.error(f"[DELETE_JOB] Error deleting job {job_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/llm/screen/start")
async def start_screening(request: StartScreeningRequest, background_tasks: BackgroundTasks):
    """Start a screening job."""
    if not MLX_AVAILABLE:
        raise HTTPException(status_code=503, detail="MLX not available")
    
    if job_manager.active_job:
        raise HTTPException(status_code=409, detail="A job is already running")
    
    # In memory-efficient mode, models don't need to be pre-loaded
    # They will be lazy-loaded on-demand during execution
    # This prevents GPU memory exhaustion
    if not model_manager.memory_efficient_mode:
        # Only check if models are loaded in performance mode
        for model_key in request.models:
            if not model_manager.is_loaded(model_key):
                raise HTTPException(status_code=400, detail=f"Model {model_key} not loaded. Enable memory-efficient mode or load models first.")
    
    job = job_manager.create_job(request)
    
    # Run in background
    background_tasks.add_task(job_manager.run_job, job.job_id, request.few_shot_examples)
    
    return {"job_id": job.job_id, "status": "started", "output_file": job.output_filename}

@app.post("/api/llm/screen/stop")
async def stop_screening(request: StopJobRequest):
    """Stop a running job."""
    logger = logging.getLogger("API")
    logger.info(f"[STOP] Received stop request for job: {request.job_id}")
    logger.info(f"[STOP] Current active job: {job_manager.active_job}")
    logger.info(f"[STOP] All jobs: {list(job_manager.jobs.keys())}")
    
    if job_manager.stop_job(request.job_id):
        logger.info(f"[STOP] Stop request successful for job: {request.job_id}")
        return {"status": "stop_requested", "job_id": request.job_id}
    
    logger.warning(f"[STOP] Stop request failed - job not found or not running: {request.job_id}")
    raise HTTPException(status_code=404, detail="Job not found or not running")

@app.get("/api/llm/jobs")
async def list_jobs(project_id: Optional[str] = Query(None, description="Filter jobs by project ID")):
    """List all jobs from memory and MongoDB."""
    # Get in-memory jobs
    memory_jobs = [asdict(job) for job in job_manager.jobs.values()]
    
    # Get jobs from MongoDB if available
    db_jobs = []
    if db is not None:
        try:
            query = {"project_id": project_id} if project_id else {}
            db_jobs = list(db["llm_jobs"].find(query, {"_id": 0}).sort("created_at", -1).limit(100))
        except Exception as e:
            logging.getLogger("API").error(f"Failed to fetch jobs from MongoDB: {e}")
    
    # Merge: prioritize memory jobs, then add DB jobs not in memory
    memory_job_ids = {job["job_id"] for job in memory_jobs}
    all_jobs = memory_jobs + [job for job in db_jobs if job["job_id"] not in memory_job_ids]
    
    # Filter by project_id if specified
    if project_id:
        all_jobs = [job for job in all_jobs if job.get("project_id") == project_id]
    
    # Add decisions_count for each job (check both by job_id and by metadata fallback)
    if db is not None:
        for job in all_jobs:
            job_id = job.get("job_id")
            # Try direct job_id match first
            decisions_count = db[LLM_DECISIONS_COLLECTION].count_documents({"job_id": job_id})
            
            # If no decisions found by job_id, try fallback (for old jobs)
            if decisions_count == 0:
                project_id_job = job.get("project_id")
                strategy = job.get("strategy") or (job.get("strategies", [])[0] if job.get("strategies") else None)
                model = job.get("model") or (job.get("models", [])[0] if job.get("models") else None)
                prompt_mode = job.get("prompt_mode")
                start_time_str = job.get("start_time")
                end_time_str = job.get("end_time")
                
                # Try timestamp-based fallback
                if project_id_job and start_time_str and end_time_str:
                    try:
                        from datetime import datetime
                        start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                        end_time = datetime.fromisoformat(end_time_str.replace('Z', '+00:00'))
                        
                        fallback_query = {
                            "project_id": project_id_job,
                            "timestamp": {"$gte": start_time, "$lte": end_time}
                        }
                        if strategy:
                            fallback_query["strategy"] = strategy
                        if model:
                            fallback_query["model"] = model
                        if prompt_mode:
                            fallback_query["prompt_mode"] = prompt_mode
                        
                        decisions_count = db[LLM_DECISIONS_COLLECTION].count_documents(fallback_query)
                    except Exception as e:
                        logging.getLogger("API").debug(f"Fallback count failed for job {job_id}: {e}")
            
            job["decisions_count"] = decisions_count
    
    return {
        "project_id": project_id,
        "total_jobs": len(all_jobs),
        "jobs": all_jobs
    }

@app.get("/api/llm/jobs/{job_id}")
async def get_job(job_id: str):
    """Get job details."""
    job = job_manager.jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return asdict(job)

@app.get("/api/llm/results/{job_id}")
async def get_results(job_id: str):
    """
    Download results file.
    
    Strategy:
    1. Try to serve local file if it exists
    2. If not, regenerate from MongoDB llm_decisions collection
    """
    logger = logging.getLogger("Results")
    
    # First try in-memory jobs
    job = job_manager.jobs.get(job_id)
    job_doc = None
    
    # If not in memory, try to find in MongoDB
    if not job and db is not None:
        job_doc = db["llm_jobs"].find_one({"job_id": job_id})
        if not job_doc:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    
    if not job and not job_doc:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Get job info
    results_file = job.results_file if job else job_doc.get("results_file")
    output_filename = job.output_filename if job else job_doc.get("output_filename")
    
    # Try to serve local file if it exists
    if results_file:
        results_path = Path(results_file).expanduser()
        if results_path.exists():
            logger.info(f"Serving local file: {results_path}")
            return FileResponse(str(results_path), filename=output_filename)
    
    # Local file doesn't exist - regenerate from MongoDB
    logger.info(f"Local file not found, regenerating from MongoDB for job {job_id}")
    
    if db is None:
        raise HTTPException(
            status_code=503, 
            detail="Cannot regenerate results: MongoDB not available"
        )
    
    # Fetch all decisions for this job from MongoDB
    decisions = list(db[LLM_DECISIONS_COLLECTION].find(
        {"job_id": job_id},
        {"_id": 0}
    ).sort("created_at", 1))
    
    if not decisions:
        raise HTTPException(
            status_code=404,
            detail=f"No results data found for job {job_id}. Results may not have been saved to MongoDB."
        )
    
    # JSON serialization helper for datetime objects
    def json_serial(obj):
        """JSON serializer for objects not serializable by default json code"""
        if isinstance(obj, datetime):
            return obj.isoformat()
        raise TypeError(f"Type {type(obj)} not serializable")
    
    # Generate temporary JSONL file
    temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False)
    try:
        for decision in decisions:
            temp_file.write(json.dumps(decision, default=json_serial) + '\n')
        temp_file.close()
        
        logger.info(f"Regenerated {len(decisions)} results for job {job_id}")
        
        # Return file with background task to delete it after sending
        def cleanup():
            try:
                os.unlink(temp_file.name)
                logger.debug(f"Cleaned up temp file: {temp_file.name}")
            except Exception as e:
                logger.error(f"Failed to cleanup temp file: {e}")
        
        background = BackgroundTasks()
        background.add_task(cleanup)
        
        return FileResponse(
            temp_file.name,
            filename=output_filename or f"results_{job_id}.jsonl",
            media_type="application/x-ndjson",
            background=background
        )
        
    except Exception as e:
        # Clean up temp file on error
        try:
            os.unlink(temp_file.name)
        except:
            pass
        raise HTTPException(status_code=500, detail=f"Failed to regenerate results: {str(e)}")

@app.get("/api/evaluate")
async def evaluate_metrics(
    project_id: str = Query(...),
    uncertain_treatment: str = Query("INCLUDE", regex="^(INCLUDE|EXCLUDE)$")
):
    """
    Calculate evaluation metrics with configurable UNCERTAIN treatment.
    
    Args:
        project_id: Project identifier
        uncertain_treatment: How to treat UNCERTAIN - "INCLUDE" or "EXCLUDE"
    
    Returns:
        Evaluation metrics (Recall, Precision, F1, WSS@95)
    """
    eval_logger = logging.getLogger("Evaluation")
    
    try:
        # Import evaluate functions
        import sys
        from pathlib import Path
        
        # Add current directory to path if needed
        current_dir = Path(__file__).parent
        if str(current_dir) not in sys.path:
            sys.path.insert(0, str(current_dir))
        
        from evaluate import get_human_ground_truth, get_llm_predictions, calculate_metrics
        
        eval_logger.info(f"Calculating metrics for project {project_id} with UNCERTAIN as {uncertain_treatment}")
        
        ground_truth = get_human_ground_truth(db, project_id)
        
        if not ground_truth:
            eval_logger.warning(f"No human decisions found for project {project_id}")
            raise HTTPException(status_code=404, detail="No human decisions found")
        
        predictions = get_llm_predictions(db, project_id)
        
        if not predictions:
            eval_logger.warning(f"No LLM predictions found for project {project_id}")
            raise HTTPException(status_code=404, detail="No LLM predictions found")
        
        metrics = calculate_metrics(
            ground_truth, 
            predictions, 
            uncertain_treatment=uncertain_treatment
        )
        
        eval_logger.info(f"Metrics calculated: {metrics}")
        
        return {
            "project_id": project_id,
            "uncertain_treatment": uncertain_treatment,
            "metrics": metrics
        }
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except ImportError as e:
        eval_logger.error(f"Failed to import evaluate module: {e}")
        raise HTTPException(status_code=500, detail=f"Evaluation module not available: {str(e)}")
    except Exception as e:
        eval_logger.error(f"Evaluation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Evaluation failed: {str(e)}")

# =============================================================================
# WEBSOCKET
# =============================================================================

@app.websocket("/ws/llm/progress")
async def websocket_progress(websocket: WebSocket):
    """WebSocket endpoint for real-time progress updates."""
    await websocket.accept()
    # Add connection only if not already present (prevent duplicates)
    if websocket not in job_manager.websocket_connections:
        job_manager.websocket_connections.append(websocket)
    job_manager.last_connection_time = time.time()  # Update connection time
    job_manager.logger.info(f"✅ WebSocket connected. Total connections: {len(job_manager.websocket_connections)}")
    
    try:
        # Send current status
        await websocket.send_json({
            "type": "connected",
            "active_job": job_manager.active_job,
            "loaded_models": model_manager.get_loaded_models(),
        })
        
        # Keep connection alive
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                # Handle ping/pong
                if data == "ping":
                    await websocket.send_text("pong")
            except asyncio.TimeoutError:
                await websocket.send_text("ping")
    except WebSocketDisconnect:
        job_manager.logger.info(f"❌ WebSocket disconnected gracefully")
    except Exception as e:
        job_manager.logger.warning(f"❌ WebSocket error: {e}")
    finally:
        if websocket in job_manager.websocket_connections:
            job_manager.websocket_connections.remove(websocket)
        job_manager.logger.info(f"📊 Remaining connections: {len(job_manager.websocket_connections)}")
        if len(job_manager.websocket_connections) == 0 and job_manager.active_job:
            job_manager.logger.warning(f"⚠️  All WebSocket connections lost! Job will auto-pause in {job_manager.connection_timeout}s if not reconnected")

"""
=============================================================================
CALCULATE METRICS ENDPOINT FOR llm_screening_api.py
=============================================================================

Two variants:
  - Variant 1: POST /api/llm/evaluate/job/{job_id} - metrics for a specific job
  - Variant 2: POST /api/llm/evaluate/compare - comparative metrics for all jobs

Author: PaSSER-SR Team
Date: February 2026
"""

# =============================================================================
# ADDITIONAL IMPORTS (if not already present above)
# =============================================================================

from collections import defaultdict
from typing import Optional, List, Dict, Any

# For Confidence Intervals (optional)
try:
    from statsmodels.stats.proportion import proportion_confint
    HAS_STATSMODELS = True
except ImportError:
    HAS_STATSMODELS = False


# =============================================================================
# PYDANTIC MODELS - DUPLICATES (see classes above)
# =============================================================================

class EvaluateJobRequest(BaseModel):
    """Request for Variant 1: metrics for a specific job"""
    uncertain_treatment: str = Field(
        default="INCLUDE",
        description="How to treat UNCERTAIN: 'INCLUDE' (conservative) or 'EXCLUDE'"
    )
    save_to_db: bool = Field(
        default=True,
        description="Whether to save results to MongoDB"
    )


class EvaluateCompareRequest(BaseModel):
    """Request for Variant 2: comparative metrics"""
    project_id: str = Field(..., description="Project ID")
    uncertain_treatment: str = Field(
        default="INCLUDE",
        description="How to treat UNCERTAIN: 'INCLUDE' (conservative) or 'EXCLUDE'"
    )
    filter_strategies: Optional[List[str]] = Field(
        default=None,
        description="Filter by strategies (e.g. ['S1_SINGLE', 'S2_MAJORITY'])"
    )
    filter_models: Optional[List[str]] = Field(
        default=None,
        description="Filter by models (e.g. ['llama-8b', 'mistral-7b'])"
    )
    filter_prompt_modes: Optional[List[str]] = Field(
        default=None,
        description="Filter by prompt mode (e.g. ['few_shot'])"
    )
    job_ids: Optional[List[str]] = Field(
        default=None,
        description="Filter by specific job IDs"
    )
    save_to_db: bool = Field(
        default=True,
        description="Whether to save results to MongoDB"
    )


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

# Collection names
GOLD_STANDARD_COLLECTION = "gold_standard"
DECISIONS_COLLECTION = "screening_decisions"
RESOLUTIONS_COLLECTION = "resolutions"
LLM_DECISIONS_COLLECTION = "llm_decisions"
EVALUATION_RESULTS_COLLECTION = "evaluation_results"


def get_human_ground_truth(db, project_id: str, include_calibration: bool = False) -> Dict[str, str]:
    """
    Extracts final human decisions for evaluation papers.

    Args:
        db: MongoDB database
        project_id: Project ID
        include_calibration: If True, includes calibration papers in ground truth (default: False)

    Priority:
    1. Resolution decision (if available)
    2. Single decision (if only one screener)
    3. Agreement between screeners

    Returns:
        Dict mapping corpus_id -> final_decision (INCLUDE/EXCLUDE/UNCERTAIN)
    """
    ground_truth = {}
    
    # Get papers - include calibration if requested
    query = {"project_id": project_id}
    if not include_calibration:
        query["is_calibration"] = {"$ne": True}
    
    eval_papers = list(db[GOLD_STANDARD_COLLECTION].find(
        query,
        {"gs_id": 1, "corpus_id": 1}
    ))
    
    eval_gs_ids = [p["gs_id"] for p in eval_papers]
    # Map gs_id -> corpus_id (corpus_id is used as key in llm_decisions)
    corpus_id_map = {p["gs_id"]: p.get("corpus_id", p["gs_id"]) for p in eval_papers}
    
    # Get all screening decisions for evaluation papers
    decisions = list(db[DECISIONS_COLLECTION].find(
        {"project_id": project_id, "gs_id": {"$in": eval_gs_ids}}
    ))
    
    # Group by gs_id
    decisions_by_paper = defaultdict(list)
    for d in decisions:
        decisions_by_paper[d["gs_id"]].append(d)
    
    # Get resolutions
    resolutions = {r["gs_id"]: r for r in db[RESOLUTIONS_COLLECTION].find(
        {"project_id": project_id, "gs_id": {"$in": eval_gs_ids}}
    )}
    
    # Determine final decision for each paper
    for gs_id in eval_gs_ids:
        paper_decisions = decisions_by_paper.get(gs_id, [])
        resolution = resolutions.get(gs_id)
        corpus_id = corpus_id_map.get(gs_id, gs_id)
        
        if resolution:
            ground_truth[corpus_id] = resolution["final_decision"]
        elif len(paper_decisions) == 1:
            ground_truth[corpus_id] = paper_decisions[0]["decision"]
        elif len(paper_decisions) >= 2:
            d1 = paper_decisions[0]["decision"]
            d2 = paper_decisions[1]["decision"]
            if d1 == d2:
                ground_truth[corpus_id] = d1
            else:
                # Disagreement without resolution
                ground_truth[corpus_id] = "UNCERTAIN"
    
    return ground_truth


def get_llm_predictions_by_job(db, job_id: str) -> Dict[str, str]:
    """
    Extracts LLM predictions for a specific job.
    
    FIXED: Handles older jobs where decisions don't have job_id field.
    Uses multiple fallback strategies with progressively looser matching.
    
    Returns:
        Dict mapping corpus_id -> predicted_decision
    """
    predictions = {}
    eval_logger = logging.getLogger("Evaluate")
    
    # Try primary query: by job_id (for newer jobs)
    decisions = list(db[LLM_DECISIONS_COLLECTION].find({"job_id": job_id}))
    
    if decisions:
        eval_logger.info(f"[PRIMARY] Found {len(decisions)} decisions with job_id={job_id}")
    else:
        # FALLBACK: If no decisions found, try to match by job metadata (for older jobs)
        eval_logger.warning(f"[FALLBACK] No decisions with job_id={job_id}, trying fallback query")
        
        # Get job metadata
        job = db["llm_jobs"].find_one({"job_id": job_id})
        if not job:
            eval_logger.error(f"[FALLBACK] Job {job_id} not found in llm_jobs collection")
            return predictions
        
        project_id = job.get("project_id")
        strategies = job.get("strategies", [])
        models = job.get("models", [])
        start_time_str = job.get("start_time")
        end_time_str = job.get("end_time")
        
        eval_logger.info(f"[FALLBACK] Job metadata: project={project_id}, strategies={strategies}, models={models}")
        eval_logger.info(f"[FALLBACK] Job times: start={start_time_str}, end={end_time_str}")
        
        # STRATEGY 1: Try with timestamp range (most specific)
        if start_time_str and end_time_str and project_id:
            try:
                from datetime import datetime
                start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                end_time = datetime.fromisoformat(end_time_str.replace('Z', '+00:00'))
                
                query1 = {
                    "project_id": project_id,
                    "timestamp": {
                        "$gte": start_time,
                        "$lte": end_time
                    }
                }
                
                # Add strategy filter if available
                if strategies and len(strategies) == 1:
                    query1["strategy"] = strategies[0]
                
                eval_logger.info(f"[FALLBACK] Strategy 1: Trying with timestamps {start_time} to {end_time}")
                decisions = list(db[LLM_DECISIONS_COLLECTION].find(query1))
                
                if decisions:
                    eval_logger.warning(f"[FALLBACK] Strategy 1 SUCCESS: Found {len(decisions)} decisions")
            except Exception as e:
                eval_logger.warning(f"[FALLBACK] Strategy 1 failed (timestamp parsing): {e}")
        
        # STRATEGY 2: Try without timestamps but with strategy (if still no results)
        if not decisions and project_id and strategies:
            query2 = {"project_id": project_id}
            
            if len(strategies) == 1:
                query2["strategy"] = strategies[0]
                eval_logger.info(f"[FALLBACK] Strategy 2: Trying project_id + strategy={strategies[0]}")
            else:
                query2["strategy"] = {"$in": strategies}
                eval_logger.info(f"[FALLBACK] Strategy 2: Trying project_id + strategies in {strategies}")
            
            decisions = list(db[LLM_DECISIONS_COLLECTION].find(query2))
            
            if decisions:
                eval_logger.warning(f"[FALLBACK] Strategy 2 SUCCESS: Found {len(decisions)} decisions")
        
        # STRATEGY 3: Try with just project_id (very loose, last resort)
        if not decisions and project_id:
            eval_logger.info(f"[FALLBACK] Strategy 3: Trying just project_id={project_id} (may return too many)")
            
            query3 = {"project_id": project_id}
            all_decisions = list(db[LLM_DECISIONS_COLLECTION].find(query3))
            
            eval_logger.warning(f"[FALLBACK] Strategy 3: Found {len(all_decisions)} total decisions for project")
            
            # Count how many LACK job_id (potential matches)
            decisions_without_job_id = [d for d in all_decisions if not d.get("job_id")]
            eval_logger.warning(f"[FALLBACK] Strategy 3: {len(decisions_without_job_id)} decisions without job_id")
            
            # If there are decisions without job_id and they're close to job's processed_papers count,
            # use them (likely this job's decisions)
            processed_papers = job.get("processed_papers", 0)
            if decisions_without_job_id:
                if len(decisions_without_job_id) > 0 and abs(len(decisions_without_job_id) - processed_papers) < 10:
                    decisions = decisions_without_job_id
                    eval_logger.warning(f"[FALLBACK] Strategy 3 SUCCESS: Using {len(decisions)} decisions (count matches job's processed_papers={processed_papers})")
                else:
                    eval_logger.warning(f"[FALLBACK] Strategy 3: Found {len(decisions_without_job_id)} decisions but count mismatch (job processed {processed_papers} papers)")
        
        if not decisions:
            eval_logger.error(f"[FALLBACK] All strategies failed - no decisions found for job {job_id}")
            eval_logger.error(f"[FALLBACK] Consider running: python3 migrate_add_job_id_to_decisions.py --migrate")
    
    # Extract predictions from decisions
    for doc in decisions:
        corpus_id = doc.get("gs_id") or doc.get("corpus_id")
        decision = doc.get("final_decision") or doc.get("decision")
        if corpus_id and decision:
            predictions[corpus_id] = decision
    
    return predictions
    
    return predictions


def get_llm_predictions_by_config(db, project_id: str, strategy: str = None, 
                                   model: str = None, prompt_mode: str = None, job_id: str = None) -> Dict[str, str]:
    """
    Extracts LLM predictions by configuration (strategy/model/prompt_mode).
    For S5, use job_id to get all predictions from both stages.
    
    Returns:
        Dict mapping corpus_id -> predicted_decision
    """
    query = {"project_id": project_id}
    
    if job_id:
        # For S5: query by job_id to get all stages
        query["job_id"] = job_id
    else:
        # For other strategies: query by model
        if model:
            query["model"] = model
    
    if strategy:
        query["strategy"] = strategy
    if prompt_mode:
        query["prompt_mode"] = prompt_mode
    
    predictions = {}
    for doc in db[LLM_DECISIONS_COLLECTION].find(query):
        corpus_id = doc.get("gs_id") or doc.get("corpus_id")
        decision = doc.get("final_decision") or doc.get("decision")
        if corpus_id and decision:
            predictions[corpus_id] = decision
    
    return predictions


def calculate_screening_metrics(ground_truth: Dict[str, str], 
                                predictions: Dict[str, str],
                                uncertain_treatment: str = "INCLUDE") -> Dict[str, Any]:
    """
    Calculates evaluation metrics for systematic review screening.

    For systematic review:
    - INCLUDE = Positive (what we are looking for)
    - EXCLUDE = Negative
    - UNCERTAIN is treated as INCLUDE (conservative for recall)

    Returns:
        Dict with metrics: TP, TN, FP, FN, Recall, Precision, F1, WSS@95
    """
    # Confusion matrix
    tp = tn = fp = fn = 0
    
    # Find common papers
    common_ids = set(ground_truth.keys()) & set(predictions.keys())
    
    if not common_ids:
        return {
            "error": "No common papers between ground truth and predictions",
            "ground_truth_count": len(ground_truth),
            "predictions_count": len(predictions)
        }
    
    # Error details (for error analysis)
    false_negatives = []  # Missed relevant papers (critical!)
    false_positives = []  # Unnecessary includes
    
    for corpus_id in common_ids:
        actual = ground_truth[corpus_id]
        predicted = predictions[corpus_id]
        
        # Treat UNCERTAIN
        if actual == "UNCERTAIN":
            actual = uncertain_treatment
        if predicted == "UNCERTAIN":
            predicted = uncertain_treatment
        
        # INCLUDE = Positive, EXCLUDE = Negative
        actual_positive = (actual == "INCLUDE")
        predicted_positive = (predicted == "INCLUDE")
        
        if actual_positive and predicted_positive:
            tp += 1
        elif not actual_positive and not predicted_positive:
            tn += 1
        elif not actual_positive and predicted_positive:
            fp += 1
            false_positives.append(corpus_id)
        else:  # actual_positive and not predicted_positive
            fn += 1
            false_negatives.append(corpus_id)
    
    # Calculate metrics
    n = len(common_ids)
    
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
    
    # WSS@95: Work Saved over Sampling at 95% recall
    # Formula: (TN + FN) / N - 0.05
    wss_95 = ((tn + fn) / n - 0.05) if n > 0 else 0.0
    
    # Specificity (True Negative Rate)
    specificity = tn / (tn + fp) if (tn + fp) > 0 else 0.0
    
    # Balanced Accuracy
    balanced_accuracy = (recall + specificity) / 2
    
    # 95% Confidence Intervals (Wilson score method)
    recall_ci = (None, None)
    precision_ci = (None, None)
    
    if HAS_STATSMODELS:
        if (tp + fn) > 0:
            recall_ci = proportion_confint(tp, tp + fn, alpha=0.05, method='wilson')
        if (tp + fp) > 0:
            precision_ci = proportion_confint(tp, tp + fp, alpha=0.05, method='wilson')
    
    return {
        # Core metrics
        "total_papers": n,
        "recall": round(recall, 4),
        "precision": round(precision, 4),
        "f1": round(f1, 4),
        "wss_95": round(wss_95, 4),
        "specificity": round(specificity, 4),
        "balanced_accuracy": round(balanced_accuracy, 4),
        
        # Threshold check
        "recall_threshold_met": recall >= 0.95,
        "recall_threshold": 0.95,
        
        # Confusion matrix
        "confusion_matrix": {
            "TP": tp,
            "TN": tn,
            "FP": fp,
            "FN": fn
        },
        
        # Distribution
        "ground_truth_distribution": {
            "INCLUDE": sum(1 for d in ground_truth.values() if d == "INCLUDE"),
            "EXCLUDE": sum(1 for d in ground_truth.values() if d == "EXCLUDE"),
            "UNCERTAIN": sum(1 for d in ground_truth.values() if d == "UNCERTAIN")
        },
        "predictions_distribution": {
            "INCLUDE": sum(1 for d in predictions.values() if d == "INCLUDE"),
            "EXCLUDE": sum(1 for d in predictions.values() if d == "EXCLUDE"),
            "UNCERTAIN": sum(1 for d in predictions.values() if d == "UNCERTAIN")
        },
        
        # Confidence Intervals
        "confidence_intervals": {
            "recall_ci_lower": round(recall_ci[0], 4) if recall_ci[0] is not None else None,
            "recall_ci_upper": round(recall_ci[1], 4) if recall_ci[1] is not None else None,
            "precision_ci_lower": round(precision_ci[0], 4) if precision_ci[0] is not None else None,
            "precision_ci_upper": round(precision_ci[1], 4) if precision_ci[1] is not None else None,
        },
        
        # Error analysis (first 10 for review)
        "error_analysis": {
            "false_negatives_count": len(false_negatives),
            "false_positives_count": len(false_positives),
            "false_negatives_sample": false_negatives[:10],
            "false_positives_sample": false_positives[:10]
        }
    }


def save_evaluation_result(db, result: Dict, project_id: str, job_id: str = None):
    """Saves evaluation result to MongoDB."""
    
    result["project_id"] = project_id
    result["evaluated_at"] = datetime.utcnow().isoformat()
    
    if job_id:
        result["job_id"] = job_id
        # Upsert by job_id
        db[EVALUATION_RESULTS_COLLECTION].update_one(
            {"job_id": job_id},
            {"$set": result},
            upsert=True
        )
    else:
        # Upsert by configuration
        filter_key = {
            "project_id": result.get("project_id"),
            "strategy": result.get("strategy"),
            "model": result.get("model"),
            "prompt_mode": result.get("prompt_mode"),
        }
        db[EVALUATION_RESULTS_COLLECTION].update_one(
            filter_key,
            {"$set": result},
            upsert=True
        )
    
    return result


def compute_s5_stage_metrics(db, project_id: str, job_id: str = None,
                              strategy: str = None, model: str = None,
                              prompt_mode: str = None) -> Optional[Dict]:
    """
    Calculates S5-specific metrics from llm_decisions in MongoDB.

    Returns:
        Dict with S5 stage metrics, or None if no S5 data available
    """
    func_logger = logging.getLogger("S5Metrics")
    
    # Build base query
    query = {"project_id": project_id, "strategy": "S5_TWO_STAGE"}
    
    # CRITICAL: Only include documents that have aggregation field (newer S5 runs)
    # Old S5 runs before the aggregation field was added will be excluded
    query["aggregation"] = {"$exists": True, "$ne": None}
    
    if job_id:
        # Simple case: query by job_id (most reliable)
        query["job_id"] = job_id
        if prompt_mode:
            query["prompt_mode"] = prompt_mode
        docs = list(db[LLM_DECISIONS_COLLECTION].find(query, {
            "aggregation": 1, "total_time": 1, "paper_id": 1, "model": 1, "job_id": 1
        }))
        func_logger.info(f"[S5 METRICS] Query by job_id={job_id}: found {len(docs)} docs")
    elif model:
        # Complex case: query by model (need to handle order variations)
        if prompt_mode:
            query["prompt_mode"] = prompt_mode
        
        # Split and sort model names for comparison
        model_set = set(m.strip() for m in model.split(','))
        
        # Find all S5 docs matching project and prompt_mode
        docs_all = list(db[LLM_DECISIONS_COLLECTION].find(query, {
            "aggregation": 1, "total_time": 1, "paper_id": 1, "model": 1, "job_id": 1
        }))
        
        func_logger.info(f"[S5 METRICS] Query without model filter: found {len(docs_all)} docs (with aggregation field)")
        
        # Filter to only docs where model set matches (regardless of order)
        docs = []
        for doc in docs_all:
            doc_model = doc.get("model", "")
            doc_model_set = set(m.strip() for m in doc_model.split(','))
            if doc_model_set == model_set:
                docs.append(doc)
        
        func_logger.info(f"[S5 METRICS] After model set filtering ({model_set}): {len(docs)} docs")
        
        # CRITICAL FIX: For S5, documents from the same job have different model values
        # (Stage 1: fast_filter only, Stage 2: all debate models)
        # So after finding matching docs, get their job_id and query ALL docs from that job
        if docs:
            job_id = docs[0].get('job_id')
            func_logger.info(f"[S5 METRICS] Found job_id={job_id}, requerying ALL docs from this job")
            
            # Query all docs from this job (both Stage 1 and Stage 2)
            query_by_job = {
                "project_id": project_id,
                "strategy": "S5_TWO_STAGE",
                "job_id": job_id,
                "aggregation": {"$exists": True, "$ne": None}
            }
            if prompt_mode:
                query_by_job["prompt_mode"] = prompt_mode
            
            docs = list(db[LLM_DECISIONS_COLLECTION].find(query_by_job, {
                "aggregation": 1, "total_time": 1, "paper_id": 1, "model": 1, "job_id": 1
            }))
            func_logger.info(f"[S5 METRICS] Requeried by job_id: found {len(docs)} total docs (Stage 1 + Stage 2)")
    else:
        # No model filter - get all S5 docs for project
        if prompt_mode:
            query["prompt_mode"] = prompt_mode
        docs = list(db[LLM_DECISIONS_COLLECTION].find(query, {
            "aggregation": 1, "total_time": 1, "paper_id": 1, "model": 1, "job_id": 1
        }))
        func_logger.info(f"[S5 METRICS] Query without model: found {len(docs)} docs")
    
    if not docs:
        func_logger.warning(f"[S5 METRICS] No documents found for query")
        return None
    
    stage1_count = 0
    stage2_count = 0
    total = 0
    total_time = 0.0
    stage1_times = []
    stage2_times = []
    model_roles = None
    
    for doc in docs:
        agg = doc.get("aggregation")
        # Aggregation should always exist due to query filter, but double-check
        if not agg:
            continue
            
        stage = agg.get("stage")
        paper_time = doc.get("total_time", 0) or 0
        
        if stage is None:
            continue
        
        total += 1
        total_time += paper_time
        
        if model_roles is None and "model_roles" in agg:
            model_roles = agg["model_roles"]
        
        if stage == 1:
            stage1_count += 1
            stage1_times.append(paper_time)
        elif stage == 2:
            stage2_count += 1
            stage2_times.append(paper_time)
    
    func_logger.info(f"[S5 METRICS] Results: St1={stage1_count}, St2={stage2_count}, Total={total}")
    
    if total == 0:
        func_logger.warning(f"[S5 METRICS] No valid stage data found")
        return None
    
    avg_st1 = (sum(stage1_times) / len(stage1_times)) if stage1_times else 0
    avg_st2 = (sum(stage2_times) / len(stage2_times)) if stage2_times else 0
    
    # Time savings: compare actual vs hypothetical all-Stage-2
    full_cost = total * avg_st2 if avg_st2 > 0 else 0
    savings_pct = ((full_cost - total_time) / full_cost * 100) if full_cost > 0 else 0
    
    result = {
        "st1_excl": stage1_count,
        "st2_papers": stage2_count,
        "st1_rate": round(stage1_count / total * 100, 1),
        "total_time_sec": round(total_time, 1),
        "avg_st1_time_sec": round(avg_st1, 2),
        "avg_st2_time_sec": round(avg_st2, 2),
        "time_savings_pct": round(savings_pct, 1),
        "debate_calls_saved": stage1_count * 2,
        "model_roles": model_roles,
    }
    
    func_logger.info(f"[S5 METRICS] Computed: {result}")
    return result


# =============================================================================
# VARIANT 1: ENDPOINT FOR METRICS OF A SPECIFIC JOB
# =============================================================================

@app.post("/api/llm/evaluate/job/{job_id}")
async def evaluate_job(job_id: str, request: EvaluateJobRequest):
    """
    Variant 1: Calculates metrics for a specific LLM screening job.

    Used for quick feedback after each test.

    Args:
        job_id: ID of the LLM screening job
        request: Parameters (uncertain_treatment, save_to_db)

    Returns:
        Metrics: Recall, Precision, F1, WSS@95, confusion matrix
    """
    eval_logger = logging.getLogger("Evaluate")
    eval_logger.info(f"[EVALUATE] Variant 1: Evaluating job {job_id}")
    
    if db is None:
        raise HTTPException(status_code=503, detail="MongoDB not available")
    
    # Check if job exists
    job = db["llm_jobs"].find_one({"job_id": job_id})
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    
    project_id = job.get("project_id")
    if not project_id:
        raise HTTPException(status_code=400, detail="Job has no project_id")
    
    # Get job's evaluation_only setting to determine if calibration papers should be included
    evaluation_only = job.get("evaluation_only", True)  # Default to excluding calibration
    include_calibration = not evaluation_only
    
    eval_logger.info(f"[EVALUATE] Job evaluation_only={evaluation_only}, include_calibration={include_calibration}")
    
    # Get ground truth - include calibration if job processed them
    ground_truth = get_human_ground_truth(db, project_id, include_calibration=include_calibration)
    if not ground_truth:
        raise HTTPException(
            status_code=400, 
            detail="No human ground truth available. Complete human screening first."
        )
    
    # Get LLM predictions for this job
    predictions = get_llm_predictions_by_job(db, job_id)
    if not predictions:
        # Provide more detailed error for debugging
        decision_count = db[LLM_DECISIONS_COLLECTION].count_documents({"job_id": job_id})
        project_decision_count = db[LLM_DECISIONS_COLLECTION].count_documents({"project_id": project_id})
        decisions_without_job_id = db[LLM_DECISIONS_COLLECTION].count_documents({
            "project_id": project_id,
            "job_id": {"$exists": False}
        })
        
        error_detail = f"No LLM predictions found for job {job_id}. "
        
        if decision_count == 0 and decisions_without_job_id > 0:
            error_detail += f"This is an older job - found {decisions_without_job_id} decisions in this project without job_id field. "
            error_detail += f"The fallback query could not match them to this job (check job's start_time, end_time, strategy fields). "
            error_detail += f"SOLUTION: Run 'python3 migrate_add_job_id_to_decisions.py --migrate' to permanently fix older jobs."
        elif decision_count == 0 and project_decision_count > 0:
            error_detail += f"Found {project_decision_count} decisions in this project but none match this job. "
            error_detail += f"The job may have crashed before saving results, or decisions were deleted."
        elif decision_count == 0:
            error_detail += f"No decisions found in database. The job may have failed to save results."
        
        eval_logger.error(f"[EVALUATE] {error_detail}")
        raise HTTPException(
            status_code=400,
            detail=error_detail
        )
    
    eval_logger.info(f"[EVALUATE] Job {job_id}: Ground truth={len(ground_truth)} papers, Predictions={len(predictions)} papers")
    
    # Check for papers in predictions but not in ground truth
    common_ids = set(ground_truth.keys()) & set(predictions.keys())
    missing_in_gt = set(predictions.keys()) - set(ground_truth.keys())
    missing_in_pred = set(ground_truth.keys()) - set(predictions.keys())
    
    if missing_in_gt:
        eval_logger.warning(f"[EVALUATE] {len(missing_in_gt)} papers in predictions but NOT in ground truth: {list(missing_in_gt)[:5]}...")
    if missing_in_pred:
        eval_logger.warning(f"[EVALUATE] {len(missing_in_pred)} papers in ground truth but NOT in predictions: {list(missing_in_pred)[:5]}...")
    
    eval_logger.info(f"[EVALUATE] Common papers for evaluation: {len(common_ids)}")
    
    # Calculate metrics
    metrics = calculate_screening_metrics(
        ground_truth,
        predictions,
        request.uncertain_treatment
    )

    # Add job metadata
    result = {
        "job_id": job_id,
        "project_id": project_id,
        "strategy": job.get("strategies", ["unknown"])[0] if job.get("strategies") else "unknown",
        "model": ','.join(job.get("models", ["unknown"])) if job.get("models") else "unknown",
        "prompt_mode": job.get("prompt_mode", "unknown"),
        "data_source": job.get("data_source", "unknown"),
        "uncertain_treatment": request.uncertain_treatment,
        "job_status": job.get("status"),
        "job_created_at": job.get("created_at"),
        "evaluation_only": evaluation_only,  # Include this for frontend display
        "includes_calibration": include_calibration,  # Include this for frontend display
        # Add coverage information
        "predictions_count": len(predictions),
        "ground_truth_count": len(ground_truth),
        "coverage_warning": len(predictions) != len(common_ids),  # True if some predictions lack ground truth
        **metrics
    }
    
    # S5-specific metrics (stage breakdown)
    strategy_name = job.get("strategies", [""])[0] if job.get("strategies") else ""
    if strategy_name == "S5_TWO_STAGE":
        s5_metrics = compute_s5_stage_metrics(db, project_id, job_id=job_id)
        if s5_metrics:
            result["s5_stage_metrics"] = s5_metrics
            eval_logger.info(f"[EVALUATE] S5 metrics: St1={s5_metrics['st1_excl']} ({s5_metrics['st1_rate']}%), "
                           f"St2={s5_metrics['st2_papers']}, Time saved={s5_metrics['time_savings_pct']}%")
    
    # Save to MongoDB if requested
    if request.save_to_db:
        save_evaluation_result(db, result, project_id, job_id)
        eval_logger.info(f"[EVALUATE] Saved evaluation result for job {job_id}")
    
    eval_logger.info(f"[EVALUATE] Job {job_id}: Recall={metrics.get('recall')}, "
                     f"Precision={metrics.get('precision')}, WSS@95={metrics.get('wss_95')}")
    
    return result


# =============================================================================
# VARIANT 2: ENDPOINT FOR COMPARATIVE METRICS
# =============================================================================

@app.post("/api/llm/evaluate/compare")
async def evaluate_compare(request: EvaluateCompareRequest):
    """
    Variant 2: Calculates comparative metrics for all strategy/model/prompt_mode combinations.

    Used for generating a comparison table for Paper 1.

    Args:
        request: Parameters including project_id and optional filters

    Returns:
        List of metrics for each combination, sorted by WSS@95 (for recall >= 0.95)
    """
    from datetime import datetime
    
    eval_logger = logging.getLogger("Evaluate")
    eval_logger.info(f"[EVALUATE] Variant 2: Comparing all strategies for project {request.project_id}")
    
    if db is None:
        raise HTTPException(status_code=503, detail="MongoDB not available")
    
    # Check if any jobs for this project include calibration papers
    # We need to match ground truth to what jobs actually processed
    jobs_for_project = list(db["llm_jobs"].find(
        {"project_id": request.project_id},
        {"evaluation_only": 1}
    ))
    
    # If ANY job has evaluation_only=False, include calibration in ground truth
    # This ensures comparison metrics match what jobs actually processed
    include_calibration = False 
    # any(not job.get("evaluation_only", True) for job in jobs_for_project)
    
    eval_logger.info(f"[EVALUATE] Found {len(jobs_for_project)} jobs for project. "
                     f"include_calibration={include_calibration}")
    
    # Get ground truth - include calibration if any job processed them
    ground_truth = get_human_ground_truth(db, request.project_id, include_calibration=include_calibration)
    if not ground_truth:
        raise HTTPException(
            status_code=400,
            detail="No human ground truth available. Complete human screening first."
        )
    
    eval_logger.info(f"[EVALUATE] Ground truth: {len(ground_truth)} papers")
    
    # Find unique combinations from llm_decisions
    # For S5, also include job_id to deduplicate properly
    match_query = {"project_id": request.project_id}
    
    # Filter by job_ids if provided
    if request.job_ids:
        eval_logger.info(f"[EVALUATE] Filtering by job_ids: {request.job_ids}")
        
        # HYBRID APPROACH: Detect which jobs have decisions with job_id field and which don't
        # Check each job individually to see if its decisions have job_id
        jobs_with_job_id = []
        jobs_without_job_id = []
        
        for jid in request.job_ids:
            test_dec = db[LLM_DECISIONS_COLLECTION].find_one(
                {"project_id": request.project_id, "job_id": jid},
                {"_id": 1}
            )
            if test_dec:
                jobs_with_job_id.append(jid)
            else:
                jobs_without_job_id.append(jid)
        
        eval_logger.info(f"[EVALUATE] Jobs with job_id field: {len(jobs_with_job_id)} - {jobs_with_job_id}")
        eval_logger.info(f"[EVALUATE] Jobs without job_id field (need fallback): {len(jobs_without_job_id)} - {jobs_without_job_id}")
        
        or_conditions = []
        
        # Part 1: Match newer jobs by job_id
        if jobs_with_job_id:
            or_conditions.append({
                "project_id": request.project_id,
                "job_id": {"$in": jobs_with_job_id}
            })
            eval_logger.info(f"[EVALUATE] Added job_id matching condition for {len(jobs_with_job_id)} newer jobs")
        
        # Part 2: Match older jobs by metadata (fallback)
        if jobs_without_job_id:
            eval_logger.warning(f"[EVALUATE] Using fallback matching for {len(jobs_without_job_id)} older jobs")
            
            # Get job metadata for older jobs only
            requested_jobs = list(db["llm_jobs"].find(
                {"job_id": {"$in": jobs_without_job_id}},
                {"strategy": 1, "strategies": 1, "model": 1, "models": 1, "prompt_mode": 1, 
                 "job_id": 1, "start_time": 1, "end_time": 1, "project_id": 1}
            ))
            
            if not requested_jobs:
                eval_logger.error(f"[EVALUATE] No job metadata found for fallback job IDs: {jobs_without_job_id}")
            else:
                # Build fallback conditions for older jobs
                for job in requested_jobs:
                    job_id = job.get("job_id")
                    project_id_job = job.get("project_id", request.project_id)
                    
                    # Get strategy - may be singular or plural field
                    strategy = job.get("strategy")
                    strategies = job.get("strategies", [])
                    if not strategy and strategies:
                        strategy = strategies[0] if len(strategies) == 1 else None
                    
                    # Get model - may be singular or plural field
                    model = job.get("model")
                    models = job.get("models", [])
                    if not model and models:
                        model = models[0] if len(models) == 1 else None
                    
                    prompt_mode = job.get("prompt_mode")
                    start_time_str = job.get("start_time")
                    end_time_str = job.get("end_time")
                    
                    eval_logger.info(f"[EVALUATE] Fallback for job {job_id}: strategy={strategy}, model={model}, mode={prompt_mode}")
                    eval_logger.info(f"[EVALUATE] Job times: {start_time_str} to {end_time_str}")
                    
                    # Strategy 1: Match by timestamp range (most specific)
                    if start_time_str and end_time_str:
                        try:
                            start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                            end_time = datetime.fromisoformat(end_time_str.replace('Z', '+00:00'))
                            
                            condition = {
                                "project_id": project_id_job,
                                "timestamp": {"$gte": start_time, "$lte": end_time}
                            }
                            if strategy:
                                condition["strategy"] = strategy
                            if model:
                                condition["model"] = model
                            if prompt_mode:
                                condition["prompt_mode"] = prompt_mode
                            
                            or_conditions.append(condition)
                            eval_logger.info(f"[EVALUATE] Added timestamp condition for old job {job_id}")
                        except Exception as e:
                            eval_logger.warning(f"[EVALUATE] Timestamp parsing failed for job {job_id}: {e}")
                    
                    # Strategy 2: Match by metadata without timestamp (broader)
                    if strategy and model and prompt_mode:
                        condition = {
                            "project_id": project_id_job,
                            "strategy": strategy,
                            "model": model,
                            "prompt_mode": prompt_mode
                        }
                        or_conditions.append(condition)
                        eval_logger.info(f"[EVALUATE] Added metadata condition for old job {job_id}")
                    elif strategy:
                        # At least match by strategy
                        condition = {
                            "project_id": project_id_job,
                            "strategy": strategy
                        }
                        or_conditions.append(condition)
                        eval_logger.info(f"[EVALUATE] Added strategy-only condition for old job {job_id}")
        
        if not or_conditions:
            raise HTTPException(
                status_code=400,
                detail=f"Could not build query conditions for jobs: {request.job_ids}"
            )
        
        # Use $or to match any of the conditions (both newer and older jobs)
        match_query = {"$or": or_conditions}
        eval_logger.info(f"[EVALUATE] Built hybrid query with {len(or_conditions)} conditions ({len(jobs_with_job_id)} newer + {len(jobs_without_job_id)} older jobs)")
    
    pipeline = [
        {"$match": match_query},
        {"$group": {
            "_id": {
                "strategy": "$strategy",
                "model": "$model",
                "prompt_mode": "$prompt_mode",
                "job_id": "$job_id"  # Include job_id for deduplication
            },
            "count": {"$sum": 1}
        }}
    ]
    
    combinations = list(db[LLM_DECISIONS_COLLECTION].aggregate(pipeline))
    eval_logger.info(f"[EVALUATE] Found {len(combinations)} combinations before deduplication")
    
    # Log what was found
    if combinations:
        for combo in combinations[:5]:  # Log first 5 for debugging
            eval_logger.info(f"[EVALUATE] Combination: {combo}")
    
    # CRITICAL: Deduplicate S5 jobs (same job_id appears with different model values for Stage 1 vs Stage 2)
    s5_jobs_seen = {}
    deduplicated_combinations = []
    
    for combo in combinations:
        config = combo["_id"]
        strategy = config.get("strategy")
        job_id = config.get("job_id")
        
        if strategy == "S5_TWO_STAGE" and job_id:
            # For S5, keep only one entry per job_id (prefer the one with more models = Stage 2)
            if job_id in s5_jobs_seen:
                # Compare model counts (Stage 2 has more models)
                existing_model = s5_jobs_seen[job_id]["_id"].get("model", "")
                current_model = config.get("model", "")
                existing_count = len(existing_model.split(','))
                current_count = len(current_model.split(','))
                
                # Keep the one with more models (Stage 2)
                if current_count > existing_count:
                    # Replace with current (has more models)
                    s5_jobs_seen[job_id] = combo
                # else: keep existing
            else:
                s5_jobs_seen[job_id] = combo
                deduplicated_combinations.append(combo)
        else:
            # Non-S5 strategies: keep as-is
            deduplicated_combinations.append(combo)
    
    # Replace S5 duplicates with deduplicated versions
    if s5_jobs_seen:
        # Remove old S5 entries
        deduplicated_combinations = [c for c in deduplicated_combinations 
                                     if not (c["_id"].get("strategy") == "S5_TWO_STAGE" and c["_id"].get("job_id"))]
        # Add deduplicated S5 entries
        deduplicated_combinations.extend(s5_jobs_seen.values())
    
    combinations = deduplicated_combinations
    
    if not combinations:
        error_msg = f"No LLM decisions found for project {request.project_id}"
        if request.job_ids:
            error_msg += f" with job IDs: {request.job_ids}. The jobs may exist but have no decisions stored, or the job IDs are incorrect."
        eval_logger.error(f"[EVALUATE] {error_msg}")
        raise HTTPException(status_code=400, detail=error_msg)
    
    eval_logger.info(f"[EVALUATE] Processing {len(combinations)} combinations after deduplication")
    
    results = []
    
    for combo in combinations:
        config = combo["_id"]
        strategy = config.get("strategy")
        model = config.get("model")
        prompt_mode = config.get("prompt_mode")
        job_id = config.get("job_id")  # For S5 deduplication
        
        if not all([strategy, model, prompt_mode]):
            continue
        
        # Apply filters if specified
        if request.filter_strategies and strategy not in request.filter_strategies:
            continue
        if request.filter_models and model not in request.filter_models:
            continue
        if request.filter_prompt_modes and prompt_mode not in request.filter_prompt_modes:
            continue
        
        # Get predictions for this combination
        # For S5: use job_id to get all stages; for others: use model
        if strategy == "S5_TWO_STAGE" and job_id:
            predictions = get_llm_predictions_by_config(
                db, request.project_id,
                strategy=strategy,
                prompt_mode=prompt_mode,
                job_id=job_id  # Get all predictions from this S5 job
            )
            # Recalculate count based on all documents from job
            combo["count"] = len(predictions)
        else:
            predictions = get_llm_predictions_by_config(
                db, request.project_id,
                strategy=strategy,
                model=model,
                prompt_mode=prompt_mode
            )
        
        if not predictions:
            continue
        
        # Calculate metrics
        metrics = calculate_screening_metrics(
            ground_truth,
            predictions,
            request.uncertain_treatment
        )
        
        result = {
            "project_id": request.project_id,
            "strategy": strategy,
            "model": model,
            "prompt_mode": prompt_mode,
            "decisions_count": combo["count"],
            "uncertain_treatment": request.uncertain_treatment,
            **metrics
        }
        
        # S5-specific metrics
        if strategy == "S5_TWO_STAGE":
            # Use job_id for accurate S5 metrics (all stages)
            s5_metrics = compute_s5_stage_metrics(
                db, request.project_id,
                strategy=strategy, model=model, prompt_mode=prompt_mode,
                job_id=job_id if job_id else None
            )
            if s5_metrics:
                result["s5_stage_metrics"] = s5_metrics
        
        results.append(result)
        
        # Save to MongoDB if requested
        if request.save_to_db:
            save_evaluation_result(db, result, request.project_id)
    
    # Sort: qualified first (recall >= 0.95) by WSS@95, then unqualified by recall
    qualified = [r for r in results if r.get("recall_threshold_met", False)]
    qualified.sort(key=lambda x: x.get("wss_95", 0), reverse=True)
    
    unqualified = [r for r in results if not r.get("recall_threshold_met", False)]
    unqualified.sort(key=lambda x: x.get("recall", 0), reverse=True)
    
    sorted_results = qualified + unqualified
    
    # Add rank
    for i, r in enumerate(sorted_results):
        r["rank"] = i + 1
        r["qualified"] = r.get("recall_threshold_met", False)
    
    eval_logger.info(f"[EVALUATE] Compared {len(sorted_results)} combinations. "
                     f"Qualified (recall>=0.95): {len(qualified)}")
    
    # Summary statistics
    summary = {
        "project_id": request.project_id,
        "total_combinations": len(sorted_results),
        "qualified_count": len(qualified),
        "unqualified_count": len(unqualified),
        "best_strategy": qualified[0] if qualified else None,
        "ground_truth_papers": len(ground_truth),
        "ground_truth_distribution": {
            "INCLUDE": sum(1 for d in ground_truth.values() if d == "INCLUDE"),
            "EXCLUDE": sum(1 for d in ground_truth.values() if d == "EXCLUDE"),
            "UNCERTAIN": sum(1 for d in ground_truth.values() if d == "UNCERTAIN")
        },
        "evaluated_at": datetime.utcnow().isoformat()
    }
    
    return {
        "summary": summary,
        "results": sorted_results
    }


# =============================================================================
# ADDITIONAL ENDPOINT: GET EVALUATION RESULTS FROM MONGODB
# =============================================================================

@app.get("/api/llm/evaluate/results")
async def get_evaluation_results(
    project_id: str = Query(..., description="Project ID"),
    job_id: Optional[str] = Query(None, description="Filter by job ID"),
    strategy: Optional[str] = Query(None, description="Filter by strategy"),
    model: Optional[str] = Query(None, description="Filter by model")
):
    """
    Returns saved evaluation results from MongoDB.
    """
    if db is None:
        raise HTTPException(status_code=503, detail="MongoDB not available")
    
    query = {"project_id": project_id}
    
    if job_id:
        query["job_id"] = job_id
    if strategy:
        query["strategy"] = strategy
    if model:
        query["model"] = model
    
    results = list(db[EVALUATION_RESULTS_COLLECTION].find(
        query, 
        {"_id": 0}
    ).sort("evaluated_at", -1))
    
    return {
        "project_id": project_id,
        "total_results": len(results),
        "results": results
    }


# =============================================================================
# ENDPOINT: DELETE EVALUATION RESULTS
# =============================================================================

@app.delete("/api/llm/evaluate/results")
async def delete_evaluation_results(
    project_id: str = Query(..., description="Project ID"),
    job_id: Optional[str] = Query(None, description="Delete only for this job ID")
):
    """
    Deletes evaluation results from MongoDB.
    """
    if db is None:
        raise HTTPException(status_code=503, detail="MongoDB not available")
    
    query = {"project_id": project_id}
    if job_id:
        query["job_id"] = job_id
    
    result = db[EVALUATION_RESULTS_COLLECTION].delete_many(query)
    
    return {
        "deleted_count": result.deleted_count,
        "project_id": project_id,
        "job_id": job_id
    }

# =============================================================================
# ERROR ANALYSIS ENDPOINT
# =============================================================================

@app.post("/api/llm/error-analysis")
async def get_error_analysis(request: ErrorAnalysisRequest):
    """
    Detailed error analysis - which criteria cause FP/FN.

    Used for:
    - Understanding why the LLM makes mistakes
    - Identifying problematic criteria
    - Paper 1, Section 4.4 Error Analysis

    Returns:
        - false_positives: list of FP examples and which criteria_met cause them
        - false_negatives: list of FN examples and which criteria_violated cause them
        - criteria_usage: overall statistics for criteria usage
    """
    global db
    if db is None:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    # 1. Get human ground truth (same function as evaluate endpoint)
    ground_truth = get_human_ground_truth(db, request.project_id)
    
    if not ground_truth:
        raise HTTPException(
            status_code=400,
            detail=f"No human ground truth found for project {request.project_id}"
        )
    
    # Treat UNCERTAIN according to the request
    for cid in list(ground_truth.keys()):
        if ground_truth[cid] == "UNCERTAIN":
            ground_truth[cid] = request.uncertain_treatment
    
    # 2. Get LLM predictions with criteria and reasoning
    # query = {"project_id": request.project_id}
    # if request.strategy:
    #     query["strategy"] = request.strategy
    # if request.model:
    #     query["model"] = request.model
    # if request.prompt_mode:
    #     query["prompt_mode"] = request.prompt_mode
    # if request.job_id:
    #     query["job_id"] = request.job_id
    query = {"project_id": request.project_id}
    if request.job_id:
        # When we have job_id, filter ONLY by it.
        # For S5 (two-stage) different stages write different strategy tags,
        # so the strategy filter would miss stage 1 decisions.
        query["job_id"] = request.job_id
    else:
        # Without job_id - filter by strategy/model/prompt_mode
        if request.strategy:
            query["strategy"] = request.strategy
        if request.model:
            query["model"] = request.model
        if request.prompt_mode:
            query["prompt_mode"] = request.prompt_mode

    predictions = {}
    for doc in db[LLM_DECISIONS_COLLECTION].find(query):
        # IMPORTANT: In llm_decisions, corpus_id can be in different fields
        corpus_id = doc.get("corpus_id") or doc.get("gs_id") or doc.get("paper_id")
        
        if not corpus_id:
            continue
        
        decision = doc.get("final_decision") or doc.get("decision")
        if decision == "UNCERTAIN":
            decision = request.uncertain_treatment
        
        predictions[corpus_id] = {
            "decision": decision,
            "criteria_met": doc.get("criteria_met", []),
            "criteria_violated": doc.get("criteria_violated", []),
            "reasoning": doc.get("reasoning", "") or doc.get("final_reasoning", "")
        }
    
    if not predictions:
        raise HTTPException(
            status_code=400,
            detail=f"No LLM predictions found for the specified filters"
        )
    
    # 3. Analyze errors
    from collections import Counter
    
    fp_criteria = Counter()  # Criteria that caused False Positives
    fn_criteria = Counter()  # Criteria that caused False Negatives
    fp_examples = []
    fn_examples = []
    fp_count = 0
    fn_count = 0
    
    # Statistics for all predictions
    all_criteria_met = Counter()
    all_criteria_violated = Counter()
    decision_counts = Counter()
    
    common_ids = set(ground_truth.keys()) & set(predictions.keys())
    
    # Get paper info for examples
    paper_info_cache = {}
    
    for corpus_id in common_ids:
        human_decision = ground_truth[corpus_id]
        llm_data = predictions[corpus_id]
        llm_decision = llm_data["decision"]
        
        # Overall statistics
        decision_counts[llm_decision] += 1
        for c in llm_data.get("criteria_met", []):
            all_criteria_met[c] += 1
        for c in llm_data.get("criteria_violated", []):
            all_criteria_violated[c] += 1
        
        human_pos = (human_decision == "INCLUDE")
        llm_pos = (llm_decision == "INCLUDE")
        
        # False Positive: LLM said INCLUDE, Human said EXCLUDE
        if not human_pos and llm_pos:
            fp_count += 1
            for c in llm_data.get("criteria_met", []):
                fp_criteria[c] += 1
            
            if len(fp_examples) < 20:
                # Get paper info if not in cache
                if corpus_id not in paper_info_cache:
                    paper = db.corpus_papers.find_one(
                        {"project_id": request.project_id, "corpus_id": corpus_id},
                        {"title": 1, "abstract": 1}
                    )
                    paper_info_cache[corpus_id] = paper or {}
                
                paper = paper_info_cache[corpus_id]
                fp_examples.append({
                    "corpus_id": corpus_id,
                    "title": paper.get("title", "N/A")[:100],
                    "criteria_met": llm_data.get("criteria_met", []),
                    "reasoning": (llm_data.get("reasoning", "") or "")[:400]
                })
        
        # False Negative: LLM said EXCLUDE, Human said INCLUDE
        elif human_pos and not llm_pos:
            fn_count += 1
            for c in llm_data.get("criteria_violated", []):
                fn_criteria[c] += 1
            
            if len(fn_examples) < 20:
                if corpus_id not in paper_info_cache:
                    paper = db.corpus_papers.find_one(
                        {"project_id": request.project_id, "corpus_id": corpus_id},
                        {"title": 1, "abstract": 1}
                    )
                    paper_info_cache[corpus_id] = paper or {}
                
                paper = paper_info_cache[corpus_id]
                fn_examples.append({
                    "corpus_id": corpus_id,
                    "title": paper.get("title", "N/A")[:100],
                    "criteria_violated": llm_data.get("criteria_violated", []),
                    "reasoning": (llm_data.get("reasoning", "") or "")[:400]
                })
    
    # 4. Generate insights
    insights = []
    
    if fp_criteria:
        top_fp = fp_criteria.most_common(1)[0]
        insights.append(
            f"IC criterion '{top_fp[0]}' caused {top_fp[1]} of {fp_count} false positives. "
            f"Consider refining this criterion in the prompt."
        )
    
    if fn_criteria:
        top_fn = fn_criteria.most_common(1)[0]
        insights.append(
            f"EC criterion '{top_fn[0]}' caused {top_fn[1]} of {fn_count} false negatives. "
            f"The model may be too aggressive in applying this exclusion criterion."
        )
    
    # Check for rarely used criteria
    for ec in ["EC4", "EC5", "EC6"]:
        if all_criteria_violated.get(ec, 0) <= 2:
            insights.append(
                f"Warning: {ec} was rarely used ({all_criteria_violated.get(ec, 0)} times). "
                f"The model may struggle with this criterion."
            )
    
    return {
        "metadata": {
            "project_id": request.project_id,
            "strategy": request.strategy,
            "model": request.model,
            "prompt_mode": request.prompt_mode,
            "uncertain_treatment": request.uncertain_treatment,
            "total_compared": len(common_ids),
            "ground_truth_count": len(ground_truth),
            "predictions_count": len(predictions)
        },
        "false_positives": {
            "count": fp_count,
            "description": "LLM said INCLUDE, Human said EXCLUDE",
            "criteria_patterns": dict(fp_criteria.most_common(10)),
            "examples": fp_examples
        },
        "false_negatives": {
            "count": fn_count,
            "description": "LLM said EXCLUDE, Human said INCLUDE (CRITICAL)",
            "criteria_patterns": dict(fn_criteria.most_common(10)),
            "examples": fn_examples
        },
        "criteria_usage": {
            "decisions": dict(decision_counts),
            "criteria_met": dict(all_criteria_met.most_common()),
            "criteria_violated": dict(all_criteria_violated.most_common())
        },
        "insights": insights
    }

# =============================================================================
# BLOCKCHAIN TEST ENDPOINT
# =============================================================================

@app.get("/api/llm/blockchain/test")
async def test_blockchain():
    """Test blockchain connectivity and configuration."""
    result = {
        "blockchain_enabled": BLOCKCHAIN_ENABLED,
        "blockchain_available": BLOCKCHAIN_AVAILABLE,
        "blockchain_endpoint": BLOCKCHAIN_ENDPOINT,
        "blockchain_contract": BLOCKCHAIN_CONTRACT,
        "has_private_key": bool(BLOCKCHAIN_PRIVATE_KEY),
        "test_status": "not_tested"
    }
    
    if not BLOCKCHAIN_ENABLED:
        result["test_status"] = "disabled"
        result["message"] = "Blockchain logging is disabled via environment variable"
        return result
    
    if not BLOCKCHAIN_AVAILABLE:
        result["test_status"] = "library_missing"
        result["message"] = "Pyntelope library not installed - run: pip install pyntelope"
        return result
    
    if not BLOCKCHAIN_PRIVATE_KEY:
        result["test_status"] = "no_key"
        result["message"] = "No blockchain private key configured"
        return result
    
    # Try to test connection
    try:
        test_data = {
            "username": "testaccount",
            "project_id": "test_project",
            "job_id": f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "strategy": "S1_SINGLE",
            "models": "test-model",
            "prompt_mode": "zero_shot",
            "papers_count": 0
        }
        
        # Don't actually send, just test transaction construction
        data_str = json.dumps(test_data, sort_keys=True)
        data_hash = hashlib.sha256(data_str.encode()).hexdigest()[:16]
        
        tx_data = [
            pyntelope.Data(name="username", value=pyntelope.types.Name(test_data["username"])),
            pyntelope.Data(name="projectid", value=pyntelope.types.String(test_data["project_id"][:32])),
            pyntelope.Data(name="jobid", value=pyntelope.types.String(test_data["job_id"][:32])),
            pyntelope.Data(name="strategy", value=pyntelope.types.String(test_data["strategy"][:16])),
            pyntelope.Data(name="models", value=pyntelope.types.String(test_data["models"][:128])),
            pyntelope.Data(name="promptmode", value=pyntelope.types.String(test_data["prompt_mode"][:32])),
            pyntelope.Data(name="papercount", value=pyntelope.types.Uint32(test_data["papers_count"])),
            pyntelope.Data(name="datahash", value=pyntelope.types.String(data_hash)),
        ]
        
        result["test_status"] = "success"
        result["message"] = "Blockchain connection configured correctly - transaction construction successful"
        result["test_data_hash"] = data_hash
        
    except Exception as e:
        result["test_status"] = "error"
        result["message"] = f"Error testing blockchain: {str(e)}"
        result["error_details"] = traceback.format_exc()
    
    return result

# =============================================================================
# MAIN
# =============================================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="PaSSER-SR LLM Screening API")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind")
    parser.add_argument("--port", type=int, default=9902, help="Port to bind")
    parser.add_argument("--cache-volume", default=None, help="SSD volume for cache (default: /Volumes/LLM or $LLM_CACHE_VOLUME)")
    parser.add_argument("--no-memory-efficient", action="store_true", 
                        help="Disable memory-efficient mode (keep all models loaded)")
    
    args = parser.parse_args()
    
    global CACHE_VOLUME, CACHE_DIRS
    
    # If cache-volume was specified on command line, reconfigure
    if args.cache_volume and args.cache_volume != CACHE_VOLUME:
        print(f"⚠️  Reconfiguring cache from {CACHE_VOLUME} to {args.cache_volume}")
        CACHE_VOLUME = args.cache_volume
        CACHE_DIRS = setup_cache_directories(CACHE_VOLUME)
        print(f"✓ Cache reconfigured to: {CACHE_VOLUME}")
    
    # Print configuration
    print("=" * 70)
    print("📦 EXTERNAL SSD CONFIGURATION")
    print("=" * 70)
    for name, path in CACHE_DIRS.items():
        print(f"   {name}: {path}")
    print("=" * 70)
    
    uvicorn.run(app, host=args.host, port=args.port)

if __name__ == "__main__":
    main()
