"""
A1 — Agreed vs. Disputed Label Performance (FIXED)
====================================================
Reviewer 2 (Major #1): Performance on agreed vs. disputed GS subsets.

FIX 1: Uses audit export for COMPLETE per-paper LLM decisions
        (original used truncated error_analysis examples).
FIX 2: Properly excludes calibration papers for few-shot configs.
FIX 3: Treats UNCERTAIN LLM decisions as INCLUDE.

Data sources
------------
1. Audit export:
   Results/Audit Export/EVoting-2026-KW_audit_export_2026-03-17.json
   → llm_decisions: per-paper LLM decisions for all configs

2. Gold Standard:
   Results/Human evaluation/EVoting-2026-KW_results_2026-02-18.json
   → 200 papers with agreement and final_decision

3. Strategy comparison:
   Results/strategy_comparison_EVoting 06-03-2026/
       strategy_comparison_EVoting-2026-KW_2026-03-06.json
   → Config list (for iterating all 28 configurations)

Output
------
CSV table + console summary.
"""

import json
import csv
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────
BASE = Path(__file__).resolve().parent.parent / "results_"
GS_PATH = BASE / "human_evaluation" / "EVoting-2026-KW_results_2026-02-18.json"
AUDIT_PATH = Path(__file__).resolve().parent / "Audit Export" / "EVoting-2026-KW_audit_export_2026-03-17.json"
STRAT_PATH = (BASE / "gold_standard_evaluation" /
              "strategy_comparison_EVoting-2026-KW_2026-03-06.json")
OUT_CSV = Path(__file__).resolve().parent / "A1_agreed_vs_disputed_results.csv"

# ── Mapping: audit llm_decisions key → (strategy, model, prompt_mode) ─
AUDIT_KEY_MAP = {
    "S1_Qwen_FS":  ("S1_SINGLE",    "qwen-7b",                        "few_shot"),
    "S5_QML_FS":   ("S5_TWO_STAGE", "qwen-7b,mistral-7b,llama-8b",    "few_shot"),
    "S5_MLQ_ZS":   ("S5_TWO_STAGE", "mistral-7b,llama-8b,qwen-7b",    "zero_shot"),
    "S2_MLQ_ZS":   ("S2_MAJORITY",  "mistral-7b,llama-8b,qwen-7b",    "zero_shot"),
    "S4_MLQ_ZS":   ("S4_CONFIDENCE","mistral-7b,llama-8b,qwen-7b",    "zero_shot"),
    "S5_LMQ_FS":   ("S5_TWO_STAGE", "llama-8b,mistral-7b,qwen-7b",    "few_shot"),
}

# Reverse map: (strategy, model, prompt_mode) → audit_key
REVERSE_MAP = {v: k for k, v in AUDIT_KEY_MAP.items()}

# ── Load data ──────────────────────────────────────────────────────────
with open(GS_PATH, "r", encoding="utf-8") as f:
    gs_data = json.load(f)

with open(AUDIT_PATH, "r", encoding="utf-8") as f:
    audit_data = json.load(f)

with open(STRAT_PATH, "r", encoding="utf-8") as f:
    strat_data = json.load(f)

# Build GS lookup
gs_lookup = {p["corpus_id"]: p for p in gs_data["papers"]}

# Identify calibration papers
hd_ids = set(h["corpus_id"] for h in audit_data["human_decisions"])
calib_ids = set(gs_lookup.keys()) - hd_ids

print(f"Gold Standard: {len(gs_lookup)} papers")
print(f"  Agreed:   {sum(1 for v in gs_lookup.values() if v['agreement'])}")
print(f"  Disputed: {sum(1 for v in gs_lookup.values() if not v['agreement'])}")
print(f"  Calibration: {len(calib_ids)} papers — {sorted(calib_ids)}")


def compute_metrics(tp, fp, fn, tn):
    """Compute recall, precision, F1."""
    recall = tp / (tp + fn) if (tp + fn) > 0 else None
    precision = tp / (tp + fp) if (tp + fp) > 0 else None
    f1 = (2 * precision * recall / (precision + recall)
          if precision and recall and (precision + recall) > 0 else None)
    return recall, precision, f1


# ── Main analysis ──────────────────────────────────────────────────────
configs = strat_data["results"]
print(f"Configurations: {len(configs)}")

results = []
available_audit_keys = set(audit_data["llm_decisions"].keys())
print(f"Audit export configs: {available_audit_keys}")

for cfg in configs:
    strategy = cfg["strategy"]
    model = cfg["model"]
    prompt = cfg["prompt_mode"]
    label = f"{strategy}|{model}|{prompt}"

    # Find matching audit key
    audit_key = REVERSE_MAP.get((strategy, model, prompt))
    if audit_key is None or audit_key not in available_audit_keys:
        print(f"  SKIP (no audit data): {label}")
        continue

    is_fs = (prompt == "few_shot")
    decisions = {d["paper_id"]: d["final_decision"]
                 for d in audit_data["llm_decisions"][audit_key]}

    counts = {
        "agreed":   {"TP": 0, "TN": 0, "FP": 0, "FN": 0},
        "disputed": {"TP": 0, "TN": 0, "FP": 0, "FN": 0},
    }

    for cid, info in gs_lookup.items():
        if is_fs and cid in calib_ids:
            continue  # Exclude calibration for few-shot

        truth = info["final_decision"]
        if truth == "UNCERTAIN":
            truth = "INCLUDE"

        pred = decisions.get(cid, "UNKNOWN")
        if pred == "UNCERTAIN":
            pred = "INCLUDE"
        if pred == "UNKNOWN":
            continue

        subset = "agreed" if info["agreement"] else "disputed"

        if pred == "INCLUDE" and truth == "INCLUDE":
            counts[subset]["TP"] += 1
        elif pred == "INCLUDE" and truth == "EXCLUDE":
            counts[subset]["FP"] += 1
        elif pred == "EXCLUDE" and truth == "INCLUDE":
            counts[subset]["FN"] += 1
        elif pred == "EXCLUDE" and truth == "EXCLUDE":
            counts[subset]["TN"] += 1

    for subset_name in ["agreed", "disputed"]:
        c = counts[subset_name]
        recall, precision, f1 = compute_metrics(c["TP"], c["FP"], c["FN"], c["TN"])
        n = c["TP"] + c["TN"] + c["FP"] + c["FN"]

        results.append({
            "strategy": strategy,
            "model": model,
            "prompt_mode": prompt,
            "subset": subset_name,
            "N": n,
            "TP": c["TP"],
            "TN": c["TN"],
            "FP": c["FP"],
            "FN": c["FN"],
            "recall": round(recall, 4) if recall is not None else "N/A",
            "precision": round(precision, 4) if precision is not None else "N/A",
            "f1": round(f1, 4) if f1 is not None else "N/A",
        })

# ── Output ─────────────────────────────────────────────────────────────
results.sort(key=lambda r: (r["strategy"], r["model"], r["prompt_mode"], r["subset"]))

fieldnames = ["strategy", "model", "prompt_mode", "subset",
              "N", "TP", "TN", "FP", "FN", "recall", "precision", "f1"]
with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(results)

print(f"\nResults written: {OUT_CSV}")

# ── Summary for top 5 ─────────────────────────────────────────────────
print("\n" + "=" * 95)
print("A1 SUMMARY — Agreed vs. Disputed performance (top 5 from Table 9)")
print("=" * 95)

TOP5_KEYS = {
    ("S1_SINGLE", "qwen-7b", "few_shot"),
    ("S5_TWO_STAGE", "qwen-7b,mistral-7b,llama-8b", "few_shot"),
    ("S5_TWO_STAGE", "mistral-7b,llama-8b,qwen-7b", "zero_shot"),
    ("S2_MAJORITY", "mistral-7b,llama-8b,qwen-7b", "zero_shot"),
    ("S4_CONFIDENCE", "mistral-7b,llama-8b,qwen-7b", "zero_shot"),
}

print(f"\n{'Config':<50} {'Subset':<10} {'N':>4} {'TP':>4} {'FP':>4} "
      f"{'FN':>4} {'TN':>4} {'Recall':>8} {'Prec':>8} {'F1':>8}")
print("-" * 95)

for r in results:
    key = (r["strategy"], r["model"], r["prompt_mode"])
    if key in TOP5_KEYS:
        label = f"{r['strategy']}|{r['model']}|{r['prompt_mode']}"
        print(f"{label:<50} {r['subset']:<10} {r['N']:>4} {r['TP']:>4} {r['FP']:>4} "
              f"{r['FN']:>4} {r['TN']:>4} {str(r['recall']):>8} {str(r['precision']):>8} "
              f"{str(r['f1']):>8}")

print("\nDone.")
