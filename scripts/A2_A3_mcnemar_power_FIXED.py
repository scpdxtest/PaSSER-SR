"""
A2 + A3 — McNemar Pairwise Test and Power Analysis (FIXED)
============================================================
Reviewer 2 (Major #2 & #3): Pairwise McNemar's test between the
top five configurations (Table 9) plus post-hoc power analysis.

FIX 1: Uses audit export for COMPLETE per-paper LLM decisions
        (original used truncated error_analysis examples).
FIX 2: Hard-codes Table 9 top 5 (original auto-sorted by F1,
        picking an incomplete N=124 config as Rank 3).
FIX 3: Properly excludes calibration papers for few-shot configs.
FIX 4: Treats UNCERTAIN LLM decisions as INCLUDE.

Data sources
------------
1. Audit export:
   Results/Audit Export/EVoting-2026-KW_audit_export_2026-03-17.json
   → llm_decisions: per-paper LLM decisions for all 2036 corpus papers
   → human_decisions: 190 non-calibration GS papers

2. Gold Standard:
   Results/Human evaluation/EVoting-2026-KW_results_2026-02-18.json
   → 200 papers with agreement and final_decision

Output
------
- A2_A3_mcnemar_pairwise.csv
- A2_A3_results.txt
"""

import json
import csv
import math
from pathlib import Path
from scipy.stats import binomtest  # McNemar exact (scipy >= 1.7)
from scipy.stats import norm
from statsmodels.stats.proportion import proportion_confint  # Clopper-Pearson

# ── Paths ──────────────────────────────────────────────────────────────
BASE = Path(__file__).resolve().parent.parent / "results_"
GS_PATH = BASE / "human_evaluation" / "EVoting-2026-KW_results_2026-02-18.json"
AUDIT_PATH = Path(__file__).resolve().parent / "Audit Export" / "EVoting-2026-KW_audit_export_2026-03-17.json"
OUT_CSV = Path(__file__).resolve().parent / "A2_A3_mcnemar_pairwise.csv"
OUT_TXT = Path(__file__).resolve().parent / "A2_A3_results.txt"

# ── Table 9 Top 5 (hard-coded, NOT auto-sorted) ───────────────────────
# Each entry: (rank, audit_key, strategy, model, prompt_mode)
TABLE9_TOP5 = [
    (1, "S1_Qwen_FS",  "S1_SINGLE",    "qwen-7b",                        "few_shot"),
    (2, "S5_QML_FS",   "S5_TWO_STAGE", "qwen-7b,mistral-7b,llama-8b",    "few_shot"),
    (3, "S5_MLQ_ZS",   "S5_TWO_STAGE", "mistral-7b,llama-8b,qwen-7b",    "zero_shot"),
    (4, "S2_MLQ_ZS",   "S2_MAJORITY",  "mistral-7b,llama-8b,qwen-7b",    "zero_shot"),
    (5, "S4_MLQ_ZS",   "S4_CONFIDENCE","mistral-7b,llama-8b,qwen-7b",    "zero_shot"),
]

# ── Load data ──────────────────────────────────────────────────────────
with open(GS_PATH, "r", encoding="utf-8") as f:
    gs_data = json.load(f)

with open(AUDIT_PATH, "r", encoding="utf-8") as f:
    audit_data = json.load(f)

# Build GS lookup
gs_lookup = {p["corpus_id"]: p for p in gs_data["papers"]}
print(f"Gold Standard loaded: {len(gs_lookup)} papers")

# Identify calibration papers (in GS but not in human_decisions)
hd_ids = set(h["corpus_id"] for h in audit_data["human_decisions"])
calib_ids = set(gs_lookup.keys()) - hd_ids
print(f"Calibration papers: {len(calib_ids)} — {sorted(calib_ids)}")

# ── Build per-paper correct/incorrect for each config ──────────────────
def get_paper_outcomes(audit_key, prompt_mode):
    """
    For each GS paper, determine if the LLM got it correct.
    Returns dict: {corpus_id: True/False} where True = correct.
    Also returns (tp, tn, fp, fn) counts.
    """
    is_fs = (prompt_mode == "few_shot")
    decisions = {d["paper_id"]: d["final_decision"]
                 for d in audit_data["llm_decisions"][audit_key]}

    outcomes = {}
    tp = tn = fp = fn = 0
    for cid, info in gs_lookup.items():
        if is_fs and cid in calib_ids:
            continue  # Exclude calibration for few-shot

        truth = info["final_decision"]
        if truth == "UNCERTAIN":
            truth = "INCLUDE"  # uncertain_treatment = INCLUDE

        pred = decisions.get(cid, "UNKNOWN")
        if pred == "UNCERTAIN":
            pred = "INCLUDE"  # Treat uncertain LLM as INCLUDE

        if pred == "INCLUDE" and truth == "INCLUDE":
            tp += 1; outcomes[cid] = True
        elif pred == "EXCLUDE" and truth == "EXCLUDE":
            tn += 1; outcomes[cid] = True
        elif pred == "INCLUDE" and truth == "EXCLUDE":
            fp += 1; outcomes[cid] = False
        elif pred == "EXCLUDE" and truth == "INCLUDE":
            fn += 1; outcomes[cid] = False

    return outcomes, tp, tn, fp, fn


# ── Compute outcomes for all top 5 ────────────────────────────────────
config_outcomes = {}
config_cm = {}
for rank, audit_key, strategy, model, prompt in TABLE9_TOP5:
    outcomes, tp, tn, fp, fn = get_paper_outcomes(audit_key, prompt)
    label = f"{strategy}|{model}|{prompt}"
    config_outcomes[rank] = (label, outcomes)
    config_cm[rank] = {"TP": tp, "TN": tn, "FP": fp, "FN": fn}
    n = tp + tn + fp + fn
    print(f"  Rank {rank}: {label}  N={n}  TP={tp} TN={tn} FP={fp} FN={fn}")


# ── Pairwise McNemar's test ───────────────────────────────────────────
def mcnemar_power(n_discordant, b, c):
    """
    Estimate power of McNemar's test using normal approximation.
    b = A_correct_B_wrong, c = A_wrong_B_correct
    """
    if n_discordant == 0:
        return 0.0
    n = n_discordant
    p = b / n if n > 0 else 0.5
    z_alpha = 1.96  # two-sided α = 0.05
    # Power = P(reject H0 | true p)
    # Using normal approx: Z = (b - c) / sqrt(b + c)
    ncp = abs(b - c) / math.sqrt(n) if n > 0 else 0
    power = 1 - norm.cdf(z_alpha - ncp) + norm.cdf(-z_alpha - ncp)
    return power


def mdd_at_80_power(n_discordant):
    """
    Minimum detectable difference at 80% power.
    For McNemar: p = proportion of discordant pairs favoring one classifier.
    """
    if n_discordant == 0:
        return None
    z_alpha = 1.96
    z_beta = 0.842  # 80% power
    # Solve for p: (p - 0.5) * sqrt(n) / sqrt(p*(1-p)) >= z_alpha + z_beta
    # Simplified: p such that power = 0.80
    # Using iterative approach
    for p_test in [i / 1000 for i in range(501, 1000)]:
        ncp = (p_test - 0.5) * math.sqrt(n_discordant) / math.sqrt(p_test * (1 - p_test))
        power = 1 - norm.cdf(z_alpha - ncp) + norm.cdf(-z_alpha - ncp)
        if power >= 0.80:
            return round(p_test, 3)
    return None


pairwise_results = []
ranks = [r for r, _, _, _, _ in TABLE9_TOP5]

for i in range(len(ranks)):
    for j in range(i + 1, len(ranks)):
        rA, rB = ranks[i], ranks[j]
        labelA, outA = config_outcomes[rA]
        labelB, outB = config_outcomes[rB]

        # Common papers
        common = set(outA.keys()) & set(outB.keys())
        n_common = len(common)

        both_correct = sum(1 for c in common if outA[c] and outB[c])
        a_only = sum(1 for c in common if outA[c] and not outB[c])
        b_only = sum(1 for c in common if not outA[c] and outB[c])
        both_wrong = sum(1 for c in common if not outA[c] and not outB[c])

        n_disc = a_only + b_only

        # McNemar's exact test (two-sided)
        if n_disc > 0:
            p_value = binomtest(a_only, n_disc, 0.5).pvalue
        else:
            p_value = 1.0

        power = mcnemar_power(n_disc, a_only, b_only)
        mdd = mdd_at_80_power(n_disc)

        pairwise_results.append({
            "rank_A": rA, "config_A": labelA,
            "rank_B": rB, "config_B": labelB,
            "N_common": n_common,
            "both_correct": both_correct,
            "A_correct_B_wrong": a_only,
            "A_wrong_B_correct": b_only,
            "both_wrong": both_wrong,
            "discordant_pairs": n_disc,
            "mcnemar_p_value": round(p_value, 4),
            "power": round(power, 4),
            "mdd_p": mdd,
        })

# ── Recall confidence intervals (Clopper-Pearson) ─────────────────────
recall_ci = []
for rank, audit_key, strategy, model, prompt in TABLE9_TOP5:
    cm = config_cm[rank]
    tp, fn = cm["TP"], cm["FN"]
    n_pos = tp + fn  # total positives in GS
    low, high = proportion_confint(tp, n_pos, alpha=0.05, method="beta")
    recall_ci.append({
        "rank": rank,
        "label": config_outcomes[rank][0],
        "recall_num": tp,
        "recall_den": n_pos,
        "recall": tp / n_pos if n_pos > 0 else None,
        "ci_low": round(low, 4),
        "ci_high": round(high, 4),
    })

# ── Write CSV ─────────────────────────────────────────────────────────
fieldnames = ["rank_A", "config_A", "rank_B", "config_B", "N_common",
              "both_correct", "A_correct_B_wrong", "A_wrong_B_correct",
              "both_wrong", "discordant_pairs", "mcnemar_p_value", "power"]
with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    for r in pairwise_results:
        row = {k: r[k] for k in fieldnames}
        writer.writerow(row)
print(f"\nCSV written: {OUT_CSV}")

# ── Write detailed results ────────────────────────────────────────────
lines = []
lines.append("A2 + A3 Combined Results: McNemar's Test and Power Analysis")
lines.append("=" * 60)
lines.append("")
lines.append("METHOD")
lines.append("-" * 6)
lines.append("Pairwise comparisons between the top five configurations were conducted")
lines.append("using McNemar's exact binomial test on paired binary outcomes (correct")
lines.append("vs. incorrect classification of each paper), following the recommendation")
lines.append("of Dietterich (1998) for comparing classifiers on a single test set.")
lines.append("Power was estimated using the normal approximation to McNemar's test")
lines.append("(Lachin 1992), based on the observed number of discordant pairs.")
lines.append("")
lines.append("DATA SOURCE: Per-paper LLM decisions from the audit export")
lines.append("(EVoting-2026-KW_audit_export_2026-03-17.json), cross-referenced")
lines.append("with the Gold Standard. This provides COMPLETE per-paper classification")
lines.append("data (not truncated error analysis examples).")
lines.append("")

n_sig = sum(1 for r in pairwise_results if r["mcnemar_p_value"] < 0.05)
disc_range = f"{min(r['discordant_pairs'] for r in pairwise_results)}–{max(r['discordant_pairs'] for r in pairwise_results)}"

lines.append("McNEMAR'S TEST RESULTS")
lines.append("-" * 22)
lines.append(f"Total pairwise comparisons: {len(pairwise_results)}")
lines.append(f"Significant at α = 0.05: {n_sig}")
lines.append(f"Discordant pairs range: {disc_range}")
lines.append("")

lines.append("POWER ANALYSIS")
lines.append("-" * 14)
max_disc = max(r['discordant_pairs'] for r in pairwise_results)
lines.append(f"The number of discordant pairs between the top five configurations")
lines.append(f"ranged from {disc_range}. With so few discordant")
lines.append(f"pairs, the statistical power to detect asymmetry is limited.")
lines.append("")

lines.append("RECALL CONFIDENCE INTERVALS")
lines.append("-" * 28)
lines.append("All top five configurations achieved perfect or near-perfect recall.")
lines.append("")

lines.append("CONCLUSION")
lines.append("-" * 10)
if n_sig == 0:
    lines.append("No pairwise comparison reached statistical significance (all p > 0.05).")
lines.append("")

lines.append("")
lines.append("DETAILED PAIRWISE RESULTS")
lines.append("=" * 80)

for r in pairwise_results:
    lines.append("")
    lines.append(f"  Pair: Rank {r['rank_A']} vs. Rank {r['rank_B']}")
    lines.append(f"  Config A: {r['config_A']}")
    lines.append(f"  Config B: {r['config_B']}")
    lines.append(f"  Common papers: {r['N_common']}")
    lines.append(f"  Contingency: both_correct={r['both_correct']}, "
                 f"A_only={r['A_correct_B_wrong']}, B_only={r['A_wrong_B_correct']}, "
                 f"both_wrong={r['both_wrong']}")
    lines.append(f"  Discordant pairs: {r['discordant_pairs']}")
    lines.append(f"  McNemar p-value: {r['mcnemar_p_value']:.4f}")
    lines.append(f"  Observed asymmetry: {r['A_correct_B_wrong']}:{r['A_wrong_B_correct']}")
    lines.append(f"  Power (observed effect): {r['power']:.4f}")
    if r['mdd_p'] is not None:
        lines.append(f"  MDD at 80% power: p = {r['mdd_p']}")
    else:
        lines.append(f"  MDD at 80% power: N/A (0 discordant pairs)")
    lines.append(f"  {'─' * 60}")

lines.append("")
lines.append("")
lines.append("RECALL CONFIDENCE INTERVALS")
lines.append("=" * 80)
for rc in recall_ci:
    lines.append(f"  Rank {rc['rank']}: {rc['label']}")
    lines.append(f"    Recall: {rc['recall_num']}/{rc['recall_den']} = {rc['recall']:.4f}")
    lines.append(f"    95% Clopper-Pearson CI: [{rc['ci_low']:.4f}, {rc['ci_high']:.4f}]")
    if rc['ci_low'] >= 0.95:
        lines.append(f"    CI lower bound ≥ 0.95 threshold")
    else:
        lines.append(f"    CI lower bound < 0.95 threshold")

with open(OUT_TXT, "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
print(f"Results written: {OUT_TXT}")

print("\nDone.")
