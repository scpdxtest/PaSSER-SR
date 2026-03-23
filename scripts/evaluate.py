#!/usr/bin/env python3
"""
PaSSER-SR Evaluation Script (Phase 7)
=====================================
Calculate evaluation metrics comparing LLM decisions with human ground truth.

Usage:
    python evaluate.py --project EVoting-2026 --output results.json

Metrics:
    - Recall (primary threshold: ≥ 0.95)
    - Precision
    - F1 Score
    - WSS@95 (Work Saved over Sampling at 95% recall)

Author: PaSSER-SR Team
Date: January 2026
"""

import os
import json
import argparse
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
try:
    from statsmodels.stats.proportion import proportion_confint
    HAS_STATSMODELS = True
except ImportError:
    HAS_STATSMODELS = False
    print("Warning: statsmodels not installed. Confidence intervals will not be calculated.")
    print("Install with: pip install statsmodels")

from pymongo import MongoClient

# Configuration
DEFAULT_MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017/")
DEFAULT_DB_NAME = os.environ.get("DB_NAME", "passer_sr")

# Collection names
GOLD_STANDARD_COLLECTION = "gold_standard"
DECISIONS_COLLECTION = "screening_decisions"
RESOLUTIONS_COLLECTION = "resolutions"
LLM_DECISIONS_COLLECTION = "llm_decisions"
EVALUATION_RESULTS_COLLECTION = "evaluation_results"


def get_human_ground_truth(db, project_id: str) -> Dict[str, str]:
    """
    Get final human decisions for evaluation papers.
    
    Priority:
    1. Resolution decision (if exists)
    2. Single screener decision (if only one)
    3. Agreement between screeners
    
    Returns:
        Dict mapping gs_id -> final_decision (INCLUDE/EXCLUDE/UNCERTAIN)
    """
    ground_truth = {}
    
    # Get evaluation papers (exclude calibration)
    eval_papers = list(db[GOLD_STANDARD_COLLECTION].find(
        {"project_id": project_id, "is_calibration": {"$ne": True}},
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
        
        # Get corpus_id for this paper (used as key in llm_decisions)
        corpus_id = corpus_id_map.get(gs_id, gs_id)
        
        if resolution:
            # Use resolution decision
            ground_truth[corpus_id] = resolution["final_decision"]
        elif len(paper_decisions) == 1:
            # Single screener
            ground_truth[corpus_id] = paper_decisions[0]["decision"]
        elif len(paper_decisions) >= 2:
            # Check agreement
            d1 = paper_decisions[0]["decision"]
            d2 = paper_decisions[1]["decision"]
            if d1 == d2:
                ground_truth[corpus_id] = d1
            else:
                # Disagreement without resolution - skip or mark as uncertain
                print(f"Warning: {gs_id} (corpus_id: {corpus_id}) has disagreement without resolution")
                ground_truth[corpus_id] = "UNCERTAIN"
        else:
            print(f"Warning: {gs_id} (corpus_id: {corpus_id}) has no decisions")
    
    return ground_truth


def get_llm_predictions(db, project_id: str, strategy: str = None, 
                        model: str = None, prompt_mode: str = None) -> Dict[str, str]:
    """
    Get LLM predictions from llm_decisions collection.
    
    Args:
        db: MongoDB database
        project_id: Project ID
        strategy: Filter by strategy (optional)
        model: Filter by model (optional)
        prompt_mode: Filter by prompt mode (optional)
    
    Returns:
        Dict mapping gs_id -> predicted_decision
    """
    query = {"project_id": project_id}
    
    if strategy:
        query["strategy"] = strategy
    if model:
        query["model"] = model
    if prompt_mode:
        query["prompt_mode"] = prompt_mode
    
    predictions = {}
    for doc in db[LLM_DECISIONS_COLLECTION].find(query):
        gs_id = doc["gs_id"]
        decision = doc.get("final_decision") or doc.get("decision")
        if decision:
            predictions[gs_id] = decision
    
    return predictions


def calculate_metrics(ground_truth: Dict[str, str], 
                      predictions: Dict[str, str],
                      uncertain_treatment: str = "INCLUDE") -> Dict[str, float]:

    """
    Calculate evaluation metrics.
    
    For systematic review screening:
    - INCLUDE = Positive (what we want to find)
    - EXCLUDE = Negative
    - UNCERTAIN treated as INCLUDE (conservative)
    
    Returns:
        Dict with metrics: TP, TN, FP, FN, Recall, Precision, F1, WSS@95
    """
    # Confusion matrix
    tp = tn = fp = fn = 0
    
    # Get common papers
    common_gs_ids = set(ground_truth.keys()) & set(predictions.keys())
    
    if not common_gs_ids:
        return {"error": "No common papers between ground truth and predictions"}
    
    for gs_id in common_gs_ids:
        actual = ground_truth[gs_id]
        predicted = predictions[gs_id]
        
        # Convert UNCERTAIN based on treatment option
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
        else:  # actual_positive and not predicted_positive
            fn += 1
    
    # Calculate metrics
    n = len(common_gs_ids)
    
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
    
    # WSS@95: Work Saved over Sampling at 95% recall
    # Formula: (TN + FN) / N - 0.05
    # Only meaningful if recall >= 0.95
    wss_95 = ((tn + fn) / n - 0.05) if n > 0 else 0.0
    
    # Calculate 95% Confidence Intervals using Wilson score method
    # Wilson score is preferred for small samples and extreme proportions (near 0 or 1)
    recall_ci = (None, None)
    precision_ci = (None, None)
    
    if HAS_STATSMODELS:
        # Recall CI: proportion of positives correctly identified
        if (tp + fn) > 0:
            recall_ci = proportion_confint(tp, tp + fn, alpha=0.05, method='wilson')
        
        # Precision CI: proportion of predicted positives that are correct
        if (tp + fp) > 0:
            precision_ci = proportion_confint(tp, tp + fp, alpha=0.05, method='wilson')
    
    return {
        "total_papers": n,
        "TP": tp,
        "TN": tn,
        "FP": fp,
        "FN": fn,
        "recall": round(recall, 4),
        "precision": round(precision, 4),
        "f1": round(f1, 4),
        "wss_95": round(wss_95, 4),
        "recall_threshold_met": recall >= 0.95,
        # Confidence Intervals (95%, Wilson score method)
        "recall_ci_lower": round(recall_ci[0], 4) if recall_ci[0] is not None else None,
        "recall_ci_upper": round(recall_ci[1], 4) if recall_ci[1] is not None else None,
        "precision_ci_lower": round(precision_ci[0], 4) if precision_ci[0] is not None else None,
        "precision_ci_upper": round(precision_ci[1], 4) if precision_ci[1] is not None else None,
    }

def compute_s5_stage_metrics(db, project_id: str, strategy: str = None,
                              model: str = None, prompt_mode: str = None) -> Optional[Dict]:
    """Compute S5-specific stage breakdown metrics from MongoDB."""
    query = {"project_id": project_id, "strategy": "S5_TWO_STAGE"}
    if model:
        query["model"] = model
    if prompt_mode:
        query["prompt_mode"] = prompt_mode
    
    docs = list(db[LLM_DECISIONS_COLLECTION].find(query, {
        "aggregation": 1, "total_time": 1
    }))
    
    if not docs:
        return None
    
    stage1_count = 0
    stage2_count = 0
    total = 0
    total_time = 0.0
    stage1_times = []
    stage2_times = []
    model_roles = None
    
    for doc in docs:
        agg = doc.get("aggregation") or {}
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
    
    if total == 0:
        return None
    
    avg_st1 = (sum(stage1_times) / len(stage1_times)) if stage1_times else 0
    avg_st2 = (sum(stage2_times) / len(stage2_times)) if stage2_times else 0
    full_cost = total * avg_st2 if avg_st2 > 0 else 0
    savings_pct = ((full_cost - total_time) / full_cost * 100) if full_cost > 0 else 0
    
    return {
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

def evaluate_all_strategies(db, project_id: str, uncertain_treatment: str = "INCLUDE") -> List[Dict]:
    """
    Evaluate all strategy+model+prompt_mode combinations.
    
    Returns:
        List of evaluation results, sorted by WSS@95 (filtered by recall >= 0.95)
    """
    # Get ground truth
    ground_truth = get_human_ground_truth(db, project_id)
    
    if not ground_truth:
        return [{"error": "No ground truth available"}]
    
    print(f"Ground truth: {len(ground_truth)} papers")
    print(f"  INCLUDE: {sum(1 for d in ground_truth.values() if d == 'INCLUDE')}")
    print(f"  EXCLUDE: {sum(1 for d in ground_truth.values() if d == 'EXCLUDE')}")
    
    # Get unique combinations from llm_decisions
    pipeline = [
        {"$match": {"project_id": project_id}},
        {"$group": {
            "_id": {
                "strategy": "$strategy",
                "model": "$model",
                "prompt_mode": "$prompt_mode"
            }
        }}
    ]
    
    combinations = list(db[LLM_DECISIONS_COLLECTION].aggregate(pipeline))
    
    results = []
    
    for combo in combinations:
        config = combo["_id"]
        strategy = config.get("strategy")
        model = config.get("model")
        prompt_mode = config.get("prompt_mode")
        
        if not all([strategy, model, prompt_mode]):
            continue
        
        # Get predictions for this combination
        predictions = get_llm_predictions(
            db, project_id, 
            strategy=strategy, 
            model=model, 
            prompt_mode=prompt_mode
        )
        
        if not predictions:
            continue
        
        # Calculate metrics
        metrics = calculate_metrics(ground_truth, predictions, uncertain_treatment)
        
        result = {
            "project_id": project_id,
            "strategy": strategy,
            "model": model,
            "prompt_mode": prompt_mode,
            "evaluated_at": datetime.utcnow().isoformat(),
            **metrics
        }

        # S5-specific stage metrics
        if strategy == "S5_TWO_STAGE":
            s5_metrics = compute_s5_stage_metrics(
                db, project_id, model=model, prompt_mode=prompt_mode
            )
            if s5_metrics:
                result["s5_stage_metrics"] = s5_metrics

        results.append(result)
    
    # Sort: filter recall >= 0.95, then sort by WSS@95 descending
    qualified = [r for r in results if r.get("recall_threshold_met", False)]
    qualified.sort(key=lambda x: x.get("wss_95", 0), reverse=True)
    
    unqualified = [r for r in results if not r.get("recall_threshold_met", False)]
    unqualified.sort(key=lambda x: x.get("recall", 0), reverse=True)
    
    return qualified + unqualified


def save_results(db, results: List[Dict], project_id: str):
    """Save evaluation results to MongoDB."""
    if not results:
        return
    
    # Create evaluation batch
    batch_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    
    for i, result in enumerate(results):
        result["batch_id"] = batch_id
        result["rank"] = i + 1 if result.get("recall_threshold_met") else None
        
        # Upsert
        filter_key = {
            "project_id": result["project_id"],
            "strategy": result["strategy"],
            "model": result["model"],
            "prompt_mode": result["prompt_mode"],
        }
        
        db[EVALUATION_RESULTS_COLLECTION].update_one(
            filter_key,
            {"$set": result},
            upsert=True
        )
    
    print(f"Saved {len(results)} evaluation results (batch: {batch_id})")


def main():
    parser = argparse.ArgumentParser(description="PaSSER-SR Evaluation Script")
    parser.add_argument("--project", required=True, help="Project ID")
    parser.add_argument("--mongo", default=DEFAULT_MONGO_URI, help="MongoDB URI")
    parser.add_argument("--db", default=DEFAULT_DB_NAME, help="Database name")
    parser.add_argument("--output", help="Output JSON file")
    parser.add_argument("--save", action="store_true", help="Save results to MongoDB")
    parser.add_argument(
        "--uncertain", 
        choices=["INCLUDE", "EXCLUDE"], 
        default="INCLUDE",
        help="How to treat UNCERTAIN decisions (default: INCLUDE)"
    )
    
    args = parser.parse_args()
    
    # Connect to MongoDB
    client = MongoClient(args.mongo, serverSelectionTimeoutMS=5000)
    db = client[args.db]
    
    print(f"\n{'='*60}")
    print(f"PaSSER-SR Evaluation: {args.project}")
    print(f"{'='*60}\n")
    
    # Run evaluation
    results = evaluate_all_strategies(db, args.project, uncertain_treatment=args.uncertain)
    
    # Print results
    print(f"\n{'='*60}")
    print("RESULTS (sorted by WSS@95 for strategies with Recall ≥ 0.95)")
    print(f"{'='*60}\n")
    
    for i, r in enumerate(results, 1):
        status = "✓" if r.get("recall_threshold_met") else "✗"
        recall = r.get('recall', None)
        precision = r.get('precision', None)
        f1 = r.get('f1', None)
        wss_95 = r.get('wss_95', None)
        
        # Format confidence intervals
        recall_ci_str = ""
        if r.get('recall_ci_lower') is not None and r.get('recall_ci_upper') is not None:
            recall_ci_str = f" (95% CI: {r['recall_ci_lower']:.1%}-{r['recall_ci_upper']:.1%})"
        
        precision_ci_str = ""
        if r.get('precision_ci_lower') is not None and r.get('precision_ci_upper') is not None:
            precision_ci_str = f" (95% CI: {r['precision_ci_lower']:.1%}-{r['precision_ci_upper']:.1%})"
    
        print(f"{i}. [{status}] {r.get('strategy')} | {r.get('model')} | {r.get('prompt_mode')}")
        print(f"   Recall: {recall:.2%}{recall_ci_str}" if isinstance(recall, (int, float)) else f"   Recall: {recall}")
        print(f"   Precision: {precision:.2%}{precision_ci_str}" if isinstance(precision, (int, float)) else f"   Precision: {precision}")
        print(f"   F1: {f1:.2%}" if isinstance(f1, (int, float)) else f"   F1: {f1}")
        print(f"   WSS@95: {wss_95:.2%}" if isinstance(wss_95, (int, float)) else f"   WSS@95: {wss_95}")
        print(f"   TP:{r.get('TP')} TN:{r.get('TN')} FP:{r.get('FP')} FN:{r.get('FN')}")
        # S5 stage breakdown
        if r.get("s5_stage_metrics"):
            s5 = r["s5_stage_metrics"]
            print(f"   S5 Stage: St1={s5['st1_excl']} filtered ({s5['st1_rate']}%), "
                  f"St2={s5['st2_papers']} debated, "
                  f"Time saved: {s5['time_savings_pct']}%")
            if s5.get("model_roles"):
                roles = s5["model_roles"]
                print(f"   Roles: FF={roles.get('fast_filter')}, Debate={roles.get('debate')}")
        print()    
        
    # Save to file
    if args.output:
        with open(args.output, "w") as f:
            json.dump(results, f, indent=2, default=str)
        print(f"Results saved to: {args.output}")
    
    # Save to MongoDB
    if args.save:
        save_results(db, results, args.project)
    
    client.close()


if __name__ == "__main__":
    main()