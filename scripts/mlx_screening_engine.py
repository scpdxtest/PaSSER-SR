#!/usr/bin/env python3
"""
PaSSER-SR MLX Screening Engine
==============================
LLM-based screening for systematic reviews using Apple MLX.

Supports 5 strategies with heterogeneous ensemble (3 different models):
- S1: Single-Agent Classification (baseline)
- S2: Majority Voting (3 agents)
- S3: Recall-Optimized Ensemble (OR logic)
- S4: Confidence-Weighted Aggregation
- S5: Two-Stage Filtering with Debate

Hardware: Optimized for Apple Silicon (M1/M2/M3)

Author: PaSSER-SR Team
Date: January 2026
Version: 1.0
"""

import os
import json
import time
import hashlib
import argparse
import re
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path
import logging

# MLX imports
try:
    from mlx_lm import load, generate
    from mlx_lm.utils import generate_step
    MLX_AVAILABLE = True
except ImportError:
    MLX_AVAILABLE = False
    print("⚠ MLX not available. Install with: pip install mlx-lm")

# MongoDB (optional)
try:
    from pymongo import MongoClient
    MONGO_AVAILABLE = True
except ImportError:
    MONGO_AVAILABLE = False

# Import screening criteria from centralized constants
from screening_criteria_constants import generate_criteria_prompt_section

# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class ModelConfig:
    """Configuration for a single LLM model."""
    name: str
    mlx_model_id: str
    max_tokens: int = 512
    temperature: float = 0.3
    top_p: float = 0.9

# Heterogeneous ensemble - 3 different models
MODELS = {
    "mistral": ModelConfig(
        name="Mistral-7B",
        mlx_model_id="mlx-community/Mistral-7B-Instruct-v0.3-4bit",
    ),
    "llama": ModelConfig(
        name="LLaMA-3.1-8B",
        mlx_model_id="mlx-community/Meta-Llama-3.1-8B-Instruct-4bit",
    ),
    "granite": ModelConfig(
        name="Granite-3.2-8B",
        # Note: If not available, use Qwen as alternative
        mlx_model_id="mlx-community/granite-3.1-8b-instruct-4bit",
    ),
}

# Alternative if Granite not available
ALTERNATIVE_MODELS = {
    "qwen": ModelConfig(
        name="Qwen-2.5-7B",
        mlx_model_id="mlx-community/Qwen2.5-7B-Instruct-4bit",
    ),
    "phi": ModelConfig(
        name="Phi-3-medium",
        mlx_model_id="mlx-community/Phi-3-medium-4k-instruct-4bit",
    ),
}

# Confidence mapping
CONFIDENCE_MAP = {
    "HIGH": 0.9,
    "MEDIUM": 0.7,
    "LOW": 0.5,
}

# =============================================================================
# ENUMS AND DATA CLASSES
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

@dataclass
class AgentResponse:
    """Response from a single LLM agent."""
    model_name: str
    decision: Decision
    confidence: Confidence
    reasoning: str
    raw_output: str
    inference_time: float
    tokens_generated: int

@dataclass
class ScreeningResult:
    """Final screening result for a paper."""
    paper_id: str
    strategy: Strategy
    final_decision: Decision
    final_confidence: Confidence
    agent_responses: List[Dict]
    aggregation_details: Dict
    total_time: float
    timestamp: str

# =============================================================================
# PROMPTS
# =============================================================================

# System prompt is dynamically generated to use centralized criteria
SYSTEM_PROMPT = f"""You are an expert systematic review screener. Your task is to classify academic papers based on title and abstract.

{generate_criteria_prompt_section()}

You must respond ONLY in the following JSON format:
{{
    "decision": "INCLUDE" or "EXCLUDE" or "UNCERTAIN",
    "confidence": "HIGH" or "MEDIUM" or "LOW",
    "reasoning": "Brief explanation (max 100 words) citing specific criteria"
}}"""

SCREENING_PROMPT_TEMPLATE = """Evaluate this paper for inclusion in a systematic review on blockchain-based electoral systems.

TITLE: {title}

ABSTRACT: {abstract}

Based on the inclusion/exclusion criteria, provide your decision in JSON format."""

DEBATE_PROMPT_TEMPLATE = """You are participating in a scholarly debate about paper inclusion.

PAPER:
Title: {title}
Abstract: {abstract}

PREVIOUS OPINIONS:
{previous_opinions}

Consider the other agents' perspectives and provide your final assessment.
You may change your decision if convinced by good arguments.
Respond in JSON format with decision, confidence, and reasoning."""

# =============================================================================
# MODEL MANAGER
# =============================================================================

class MLXModelManager:
    """Manages loading and inference for MLX models."""
    
    def __init__(self, cache_dir: Optional[str] = None):
        self.models: Dict[str, Tuple[Any, Any]] = {}  # (model, tokenizer)
        self.cache_dir = cache_dir or os.path.expanduser("~/.cache/mlx_models")
        self.logger = logging.getLogger("MLXModelManager")
        
    def load_model(self, model_key: str) -> bool:
        """Load a model into memory."""
        if model_key in self.models:
            self.logger.info(f"Model {model_key} already loaded")
            return True
            
        if model_key not in MODELS:
            if model_key in ALTERNATIVE_MODELS:
                config = ALTERNATIVE_MODELS[model_key]
            else:
                self.logger.error(f"Unknown model: {model_key}")
                return False
        else:
            config = MODELS[model_key]
            
        try:
            self.logger.info(f"Loading {config.name} from {config.mlx_model_id}...")
            start = time.time()
            model, tokenizer = load(config.mlx_model_id)
            load_time = time.time() - start
            self.models[model_key] = (model, tokenizer, config)
            self.logger.info(f"✓ Loaded {config.name} in {load_time:.1f}s")
            return True
        except Exception as e:
            self.logger.error(f"Failed to load {model_key}: {e}")
            return False
    
    def load_all_models(self) -> bool:
        """Load all models in the ensemble."""
        success = True
        for key in MODELS.keys():
            if not self.load_model(key):
                # Try alternative
                self.logger.warning(f"Trying alternative for {key}")
                alt_key = list(ALTERNATIVE_MODELS.keys())[0]
                if not self.load_model(alt_key):
                    success = False
        return success
    
    def generate(
        self, 
        model_key: str, 
        prompt: str,
        max_tokens: int = 512,
        temperature: float = 0.3,
    ) -> Tuple[str, float, int]:
        """Generate text with a model. Returns (text, time, tokens)."""
        if model_key not in self.models:
            raise ValueError(f"Model {model_key} not loaded")
            
        model, tokenizer, config = self.models[model_key]
        
        start = time.time()
        response = generate(
            model,
            tokenizer,
            prompt=prompt,
            max_tokens=max_tokens,
            temp=temperature,
            verbose=False,
        )
        elapsed = time.time() - start
        
        # Estimate tokens (rough)
        tokens = len(response.split()) * 1.3
        
        return response, elapsed, int(tokens)
    
    def unload_model(self, model_key: str):
        """Unload a model to free memory."""
        if model_key in self.models:
            del self.models[model_key]
            self.logger.info(f"Unloaded {model_key}")

# =============================================================================
# RESPONSE PARSER
# =============================================================================

def parse_llm_response(raw_output: str) -> Tuple[Decision, Confidence, str]:
    """Parse LLM JSON response into structured data."""
    
    # Try to find JSON in the response
    json_match = re.search(r'\{[^{}]*\}', raw_output, re.DOTALL)
    
    if json_match:
        try:
            data = json.loads(json_match.group())
            decision = Decision(data.get("decision", "UNCERTAIN").upper())
            confidence = Confidence(data.get("confidence", "LOW").upper())
            reasoning = data.get("reasoning", "No reasoning provided")
            return decision, confidence, reasoning
        except (json.JSONDecodeError, ValueError):
            pass
    
    # Fallback: pattern matching
    raw_upper = raw_output.upper()
    
    if "INCLUDE" in raw_upper:
        decision = Decision.INCLUDE
    elif "EXCLUDE" in raw_upper:
        decision = Decision.EXCLUDE
    else:
        decision = Decision.UNCERTAIN
    
    if "HIGH" in raw_upper:
        confidence = Confidence.HIGH
    elif "MEDIUM" in raw_upper:
        confidence = Confidence.MEDIUM
    else:
        confidence = Confidence.LOW
    
    return decision, confidence, raw_output[:200]

# =============================================================================
# SCREENING STRATEGIES
# =============================================================================

class ScreeningEngine:
    """Main screening engine implementing all 5 strategies."""
    
    def __init__(
        self,
        model_manager: MLXModelManager,
        output_dir: str = "./screening_results",
        mongo_uri: Optional[str] = None,
        db_name: str = "passer_sr",
    ):
        self.model_manager = model_manager
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger("ScreeningEngine")
        
        # MongoDB connection (optional)
        self.db = None
        if mongo_uri and MONGO_AVAILABLE:
            try:
                client = MongoClient(mongo_uri)
                self.db = client[db_name]
                self.logger.info(f"✓ Connected to MongoDB: {db_name}")
            except Exception as e:
                self.logger.warning(f"MongoDB connection failed: {e}")
    
    def _build_prompt(self, title: str, abstract: str, model_key: str) -> str:
        """Build the full prompt for a model."""
        config = MODELS.get(model_key) or ALTERNATIVE_MODELS.get(model_key)
        
        # Different models may need different prompt formats
        if "llama" in model_key.lower():
            return f"""<|begin_of_text|><|start_header_id|>system<|end_header_id|>

{SYSTEM_PROMPT}<|eot_id|><|start_header_id|>user<|end_header_id|>

{SCREENING_PROMPT_TEMPLATE.format(title=title, abstract=abstract)}<|eot_id|><|start_header_id|>assistant<|end_header_id|>

"""
        elif "mistral" in model_key.lower():
            return f"""[INST] {SYSTEM_PROMPT}

{SCREENING_PROMPT_TEMPLATE.format(title=title, abstract=abstract)} [/INST]"""
        else:
            # Generic format for Granite, Qwen, etc.
            return f"""<|system|>
{SYSTEM_PROMPT}<|end|>
<|user|>
{SCREENING_PROMPT_TEMPLATE.format(title=title, abstract=abstract)}<|end|>
<|assistant|>
"""
    
    def _call_agent(
        self, 
        model_key: str, 
        title: str, 
        abstract: str,
        custom_prompt: Optional[str] = None,
    ) -> AgentResponse:
        """Call a single agent and parse response."""
        
        prompt = custom_prompt or self._build_prompt(title, abstract, model_key)
        
        try:
            raw_output, elapsed, tokens = self.model_manager.generate(
                model_key, 
                prompt,
                max_tokens=512,
                temperature=0.3,
            )
            
            decision, confidence, reasoning = parse_llm_response(raw_output)
            
            config = MODELS.get(model_key) or ALTERNATIVE_MODELS.get(model_key)
            
            return AgentResponse(
                model_name=config.name,
                decision=decision,
                confidence=confidence,
                reasoning=reasoning,
                raw_output=raw_output,
                inference_time=elapsed,
                tokens_generated=tokens,
            )
        except Exception as e:
            self.logger.error(f"Agent {model_key} failed: {e}")
            config = MODELS.get(model_key) or ALTERNATIVE_MODELS.get(model_key)
            return AgentResponse(
                model_name=config.name,
                decision=Decision.UNCERTAIN,
                confidence=Confidence.LOW,
                reasoning=f"Error: {str(e)}",
                raw_output="",
                inference_time=0,
                tokens_generated=0,
            )
    
    # -------------------------------------------------------------------------
    # Strategy S1: Single-Agent Classification
    # -------------------------------------------------------------------------
    
    def s1_single_agent(
        self, 
        paper_id: str, 
        title: str, 
        abstract: str,
        model_key: str = "mistral",
    ) -> ScreeningResult:
        """S1: Single agent classification (baseline)."""
        
        start = time.time()
        response = self._call_agent(model_key, title, abstract)
        
        return ScreeningResult(
            paper_id=paper_id,
            strategy=Strategy.S1_SINGLE,
            final_decision=response.decision,
            final_confidence=response.confidence,
            agent_responses=[asdict(response)],
            aggregation_details={"model": model_key},
            total_time=time.time() - start,
            timestamp=datetime.now().isoformat(),
        )
    
    # -------------------------------------------------------------------------
    # Strategy S2: Majority Voting
    # -------------------------------------------------------------------------
    
    def s2_majority_voting(
        self, 
        paper_id: str, 
        title: str, 
        abstract: str,
    ) -> ScreeningResult:
        """S2: Majority voting with heterogeneous ensemble."""
        
        start = time.time()
        responses = []
        
        # Call all 3 agents
        for model_key in self.model_manager.models.keys():
            response = self._call_agent(model_key, title, abstract)
            responses.append(response)
        
        # Count votes
        votes = {"INCLUDE": 0, "EXCLUDE": 0, "UNCERTAIN": 0}
        for r in responses:
            votes[r.decision.value] += 1
        
        # Majority decision
        if votes["INCLUDE"] >= 2:
            final_decision = Decision.INCLUDE
        elif votes["EXCLUDE"] >= 2:
            final_decision = Decision.EXCLUDE
        else:
            final_decision = Decision.UNCERTAIN
        
        # Average confidence
        conf_values = [CONFIDENCE_MAP[r.confidence.value] for r in responses]
        avg_conf = sum(conf_values) / len(conf_values)
        
        if avg_conf >= 0.85:
            final_confidence = Confidence.HIGH
        elif avg_conf >= 0.65:
            final_confidence = Confidence.MEDIUM
        else:
            final_confidence = Confidence.LOW
        
        return ScreeningResult(
            paper_id=paper_id,
            strategy=Strategy.S2_MAJORITY,
            final_decision=final_decision,
            final_confidence=final_confidence,
            agent_responses=[asdict(r) for r in responses],
            aggregation_details={
                "votes": votes,
                "avg_confidence": avg_conf,
            },
            total_time=time.time() - start,
            timestamp=datetime.now().isoformat(),
        )
    
    # -------------------------------------------------------------------------
    # Strategy S3: Recall-Optimized (OR logic)
    # -------------------------------------------------------------------------
    
    def s3_recall_optimized(
        self, 
        paper_id: str, 
        title: str, 
        abstract: str,
    ) -> ScreeningResult:
        """S3: Recall-optimized ensemble (any INCLUDE = INCLUDE)."""
        
        start = time.time()
        responses = []
        
        # Call all 3 agents
        for model_key in self.model_manager.models.keys():
            response = self._call_agent(model_key, title, abstract)
            responses.append(response)
        
        # OR logic: any INCLUDE means INCLUDE
        has_include = any(r.decision == Decision.INCLUDE for r in responses)
        has_uncertain = any(r.decision == Decision.UNCERTAIN for r in responses)
        
        if has_include:
            final_decision = Decision.INCLUDE
        elif has_uncertain:
            final_decision = Decision.UNCERTAIN
        else:
            final_decision = Decision.EXCLUDE
        
        # Confidence: highest among those supporting final decision
        supporting = [r for r in responses if r.decision == final_decision]
        if supporting:
            conf_values = [CONFIDENCE_MAP[r.confidence.value] for r in supporting]
            max_conf = max(conf_values)
        else:
            max_conf = 0.5
        
        if max_conf >= 0.85:
            final_confidence = Confidence.HIGH
        elif max_conf >= 0.65:
            final_confidence = Confidence.MEDIUM
        else:
            final_confidence = Confidence.LOW
        
        return ScreeningResult(
            paper_id=paper_id,
            strategy=Strategy.S3_RECALL_OPT,
            final_decision=final_decision,
            final_confidence=final_confidence,
            agent_responses=[asdict(r) for r in responses],
            aggregation_details={
                "has_include": has_include,
                "has_uncertain": has_uncertain,
                "or_logic": "any INCLUDE → INCLUDE",
            },
            total_time=time.time() - start,
            timestamp=datetime.now().isoformat(),
        )
    
    # -------------------------------------------------------------------------
    # Strategy S4: Confidence-Weighted Aggregation
    # -------------------------------------------------------------------------
    
    def s4_confidence_weighted(
        self, 
        paper_id: str, 
        title: str, 
        abstract: str,
    ) -> ScreeningResult:
        """S4: Confidence-weighted aggregation."""
        
        start = time.time()
        responses = []
        
        # Call all 3 agents
        for model_key in self.model_manager.models.keys():
            response = self._call_agent(model_key, title, abstract)
            responses.append(response)
        
        # Weighted voting
        # INCLUDE = +1, EXCLUDE = -1, UNCERTAIN = 0
        weighted_score = 0
        total_weight = 0
        
        for r in responses:
            weight = CONFIDENCE_MAP[r.confidence.value]
            total_weight += weight
            
            if r.decision == Decision.INCLUDE:
                weighted_score += weight
            elif r.decision == Decision.EXCLUDE:
                weighted_score -= weight
            # UNCERTAIN adds 0
        
        # Normalize
        normalized_score = weighted_score / total_weight if total_weight > 0 else 0
        
        # Thresholds for decision
        if normalized_score > 0.2:
            final_decision = Decision.INCLUDE
        elif normalized_score < -0.2:
            final_decision = Decision.EXCLUDE
        else:
            final_decision = Decision.UNCERTAIN
        
        # Confidence based on agreement
        decisions = [r.decision for r in responses]
        if all(d == final_decision for d in decisions):
            final_confidence = Confidence.HIGH
        elif decisions.count(final_decision) >= 2:
            final_confidence = Confidence.MEDIUM
        else:
            final_confidence = Confidence.LOW
        
        return ScreeningResult(
            paper_id=paper_id,
            strategy=Strategy.S4_CONFIDENCE,
            final_decision=final_decision,
            final_confidence=final_confidence,
            agent_responses=[asdict(r) for r in responses],
            aggregation_details={
                "weighted_score": weighted_score,
                "normalized_score": normalized_score,
                "total_weight": total_weight,
            },
            total_time=time.time() - start,
            timestamp=datetime.now().isoformat(),
        )
    
    # -------------------------------------------------------------------------
    # Strategy S5: Two-Stage Filtering with Debate
    # -------------------------------------------------------------------------
    
    def s5_two_stage_debate(
        self, 
        paper_id: str, 
        title: str, 
        abstract: str,
        fast_filter_model: str = "mistral",
    ) -> ScreeningResult:
        """S5: Two-stage filtering with debate for uncertain cases."""
        
        start = time.time()
        all_responses = []
        
        # Stage 1: Fast filter
        stage1_response = self._call_agent(fast_filter_model, title, abstract)
        all_responses.append(stage1_response)
        
        # If HIGH confidence EXCLUDE → done
        if (stage1_response.decision == Decision.EXCLUDE and 
            stage1_response.confidence == Confidence.HIGH):
            
            return ScreeningResult(
                paper_id=paper_id,
                strategy=Strategy.S5_TWO_STAGE,
                final_decision=Decision.EXCLUDE,
                final_confidence=Confidence.HIGH,
                agent_responses=[asdict(stage1_response)],
                aggregation_details={
                    "stage": 1,
                    "fast_filter_model": fast_filter_model,
                    "reason": "High-confidence EXCLUDE in Stage 1",
                },
                total_time=time.time() - start,
                timestamp=datetime.now().isoformat(),
            )
        
        # Stage 2: Debate with remaining models
        other_models = [k for k in self.model_manager.models.keys() if k != fast_filter_model]
        
        # First round: independent opinions
        stage2_responses = []
        for model_key in other_models:
            response = self._call_agent(model_key, title, abstract)
            stage2_responses.append((model_key, response))
            all_responses.append(response)
        
        # Check for consensus
        all_decisions = [stage1_response.decision] + [r.decision for _, r in stage2_responses]
        
        if len(set(all_decisions)) == 1:
            # Consensus reached
            final_decision = all_decisions[0]
            final_confidence = Confidence.HIGH
        else:
            # Debate round
            previous_opinions = "\n".join([
                f"- {stage1_response.model_name}: {stage1_response.decision.value} "
                f"(Confidence: {stage1_response.confidence.value}) - {stage1_response.reasoning[:100]}"
            ] + [
                f"- {r.model_name}: {r.decision.value} "
                f"(Confidence: {r.confidence.value}) - {r.reasoning[:100]}"
                for _, r in stage2_responses
            ])
            
            # Ask strongest model to adjudicate
            debate_prompt = DEBATE_PROMPT_TEMPLATE.format(
                title=title,
                abstract=abstract,
                previous_opinions=previous_opinions,
            )
            
            # Use the model with highest confidence
            all_with_conf = [(stage1_response, fast_filter_model)] + \
                           [(r, k) for k, r in stage2_responses]
            
            best_model_key = max(
                all_with_conf, 
                key=lambda x: CONFIDENCE_MAP[x[0].confidence.value]
            )[1]
            
            config = MODELS.get(best_model_key) or ALTERNATIVE_MODELS.get(best_model_key)
            
            # Build debate prompt with model-specific format
            if "llama" in best_model_key.lower():
                full_debate_prompt = f"""<|begin_of_text|><|start_header_id|>system<|end_header_id|>

{SYSTEM_PROMPT}<|eot_id|><|start_header_id|>user<|end_header_id|>

{debate_prompt}<|eot_id|><|start_header_id|>assistant<|end_header_id|>

"""
            elif "mistral" in best_model_key.lower():
                full_debate_prompt = f"""[INST] {SYSTEM_PROMPT}

{debate_prompt} [/INST]"""
            else:
                full_debate_prompt = f"""<|system|>
{SYSTEM_PROMPT}<|end|>
<|user|>
{debate_prompt}<|end|>
<|assistant|>
"""
            
            debate_response = self._call_agent(
                best_model_key, 
                title, 
                abstract,
                custom_prompt=full_debate_prompt,
            )
            all_responses.append(debate_response)
            
            final_decision = debate_response.decision
            final_confidence = debate_response.confidence
        
        return ScreeningResult(
            paper_id=paper_id,
            strategy=Strategy.S5_TWO_STAGE,
            final_decision=final_decision,
            final_confidence=final_confidence,
            agent_responses=[asdict(r) for r in all_responses],
            aggregation_details={
                "stage": 2,
                "fast_filter_model": fast_filter_model,
                "had_debate": len(all_responses) > 3,
                "final_decisions": [d.value for d in all_decisions],
            },
            total_time=time.time() - start,
            timestamp=datetime.now().isoformat(),
        )
    
    # -------------------------------------------------------------------------
    # Batch Processing
    # -------------------------------------------------------------------------
    
    def screen_paper(
        self, 
        paper: Dict, 
        strategies: List[Strategy],
    ) -> Dict[str, ScreeningResult]:
        """Screen a single paper with specified strategies."""
        
        paper_id = paper.get("corpus_id") or paper.get("_id") or paper.get("id")
        title = paper.get("title", "")
        abstract = paper.get("abstract", "")
        
        if not title or not abstract:
            self.logger.warning(f"Paper {paper_id} missing title or abstract")
            return {}
        
        results = {}
        
        for strategy in strategies:
            try:
                if strategy == Strategy.S1_SINGLE:
                    # Run S1 for each model separately
                    for model_key in self.model_manager.models.keys():
                        result = self.s1_single_agent(paper_id, title, abstract, model_key)
                        results[f"S1_{model_key}"] = result
                elif strategy == Strategy.S2_MAJORITY:
                    results["S2"] = self.s2_majority_voting(paper_id, title, abstract)
                elif strategy == Strategy.S3_RECALL_OPT:
                    results["S3"] = self.s3_recall_optimized(paper_id, title, abstract)
                elif strategy == Strategy.S4_CONFIDENCE:
                    results["S4"] = self.s4_confidence_weighted(paper_id, title, abstract)
                elif strategy == Strategy.S5_TWO_STAGE:
                    results["S5"] = self.s5_two_stage_debate(paper_id, title, abstract)
            except Exception as e:
                self.logger.error(f"Strategy {strategy} failed for {paper_id}: {e}")
        
        return results
    
    def screen_corpus(
        self,
        corpus: List[Dict],
        strategies: List[Strategy] = None,
        save_interval: int = 50,
        resume_from: int = 0,
    ) -> str:
        """Screen entire corpus with all strategies."""
        
        if strategies is None:
            strategies = list(Strategy)
        
        total = len(corpus)
        results_file = self.output_dir / f"screening_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
        
        self.logger.info(f"Starting screening of {total} papers with strategies: {[s.value for s in strategies]}")
        self.logger.info(f"Results will be saved to: {results_file}")
        
        processed = 0
        start_time = time.time()
        
        with open(results_file, "a") as f:
            for i, paper in enumerate(corpus[resume_from:], start=resume_from):
                paper_id = paper.get("corpus_id") or paper.get("_id") or f"paper_{i}"
                
                try:
                    results = self.screen_paper(paper, strategies)
                    
                    for strategy_key, result in results.items():
                        record = {
                            "paper_id": paper_id,
                            "strategy": strategy_key,
                            **asdict(result),
                        }
                        f.write(json.dumps(record) + "\n")
                    
                    processed += 1
                    
                    # Progress report
                    if processed % 10 == 0:
                        elapsed = time.time() - start_time
                        rate = processed / elapsed
                        eta = (total - resume_from - processed) / rate if rate > 0 else 0
                        self.logger.info(
                            f"Progress: {processed}/{total-resume_from} "
                            f"({100*processed/(total-resume_from):.1f}%) "
                            f"| Rate: {rate:.2f} papers/sec "
                            f"| ETA: {eta/3600:.1f}h"
                        )
                    
                    # Save checkpoint
                    if processed % save_interval == 0:
                        f.flush()
                        self.logger.info(f"Checkpoint saved at paper {i}")
                        
                except Exception as e:
                    self.logger.error(f"Failed to process paper {paper_id}: {e}")
                    continue
        
        total_time = time.time() - start_time
        self.logger.info(f"✓ Screening complete: {processed} papers in {total_time/3600:.2f}h")
        self.logger.info(f"Results saved to: {results_file}")
        
        return str(results_file)

# =============================================================================
# MAIN
# =============================================================================

def setup_logging(log_file: Optional[str] = None):
    """Configure logging."""
    handlers = [logging.StreamHandler()]
    if log_file:
        handlers.append(logging.FileHandler(log_file))
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
        handlers=handlers,
    )

def main():
    parser = argparse.ArgumentParser(description="PaSSER-SR MLX Screening Engine")
    parser.add_argument("--corpus", required=True, help="Path to corpus JSON file")
    parser.add_argument("--output", default="./screening_results", help="Output directory")
    parser.add_argument("--strategies", nargs="+", default=["S1", "S2", "S3", "S4", "S5"],
                       help="Strategies to run (S1, S2, S3, S4, S5)")
    parser.add_argument("--resume", type=int, default=0, help="Resume from paper index")
    parser.add_argument("--mongo-uri", help="MongoDB URI (optional)")
    parser.add_argument("--log", help="Log file path")
    
    args = parser.parse_args()
    
    setup_logging(args.log)
    logger = logging.getLogger("main")
    
    if not MLX_AVAILABLE:
        logger.error("MLX not available. Please install: pip install mlx-lm")
        return
    
    # Load corpus
    logger.info(f"Loading corpus from {args.corpus}")
    with open(args.corpus, "r") as f:
        if args.corpus.endswith(".jsonl"):
            corpus = [json.loads(line) for line in f]
        else:
            corpus = json.load(f)
    logger.info(f"Loaded {len(corpus)} papers")
    
    # Initialize model manager
    model_manager = MLXModelManager()
    
    # Load all models
    logger.info("Loading models...")
    if not model_manager.load_all_models():
        logger.error("Failed to load some models")
        return
    
    # Initialize screening engine
    engine = ScreeningEngine(
        model_manager=model_manager,
        output_dir=args.output,
        mongo_uri=args.mongo_uri,
    )
    
    # Map strategy names
    strategy_map = {
        "S1": Strategy.S1_SINGLE,
        "S2": Strategy.S2_MAJORITY,
        "S3": Strategy.S3_RECALL_OPT,
        "S4": Strategy.S4_CONFIDENCE,
        "S5": Strategy.S5_TWO_STAGE,
    }
    
    strategies = [strategy_map[s] for s in args.strategies if s in strategy_map]
    
    # Run screening
    results_file = engine.screen_corpus(
        corpus=corpus,
        strategies=strategies,
        resume_from=args.resume,
    )
    
    logger.info(f"Done! Results saved to: {results_file}")

if __name__ == "__main__":
    main()
