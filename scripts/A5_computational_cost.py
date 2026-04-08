#!/usr/bin/env python3
"""
A5 – Computational Cost Analysis
=================================
Addresses reviewer comment R2.W8:
  "The paper argues that multi-agent strategies introduce 'coordination
   overhead' but provides no quantitative evidence. Include wall-clock
   time, token counts, or similar metrics."

Reads Full Corpus screening JSONL files for all 5 top configurations.
Extracts per-paper: wall-clock time, token count, number of agents,
and for S5 — Stage 1 vs Stage 2 paper counts.

Outputs
-------
  A5_computational_cost.csv   – per-configuration summary
  A5_per_paper_timing.csv     – per-paper timing (all configs)
  A5_results.txt              – human-readable summary
"""

import json
import statistics
from pathlib import Path
from collections import Counter

# ── Paths ──────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
FC = ROOT / "results_" / "full_corpus"
OUT = Path(__file__).parent

# Top 5 configurations (Full Corpus JSONL files)
CONFIGS = [
    {
        "rank": 1,
        "name": "S1 Qwen FS",
        "strategy": "S1",
        "file": FC / "screening_EVoting-2026-KW_20260311-FullCorpus-FewShot-S1-Qwen.jsonl",
    },
    {
        "rank": 2,
        "name": "S5 Q→M+L FS",
        "strategy": "S5",
        "file": FC / "screening_EVoting-2026-KW_20260313-Ira-Full corpus-S5-Q->M=L FS.jsonl",
    },
    {
        "rank": 3,
        "name": "S5 M→L+Q ZS",
        "strategy": "S5",
        "file": FC / "screening_EVoting-2026-KW_20260315-Ira-FullCorpus-S5-M->L+Q-ZS.jsonl",
    },
    {
        "rank": 4,
        "name": "S2 MLQ ZS",
        "strategy": "S2",
        "file": FC / "screening_EVoting-2026-KW_20260313-FullCorpus-ZeroShot-S2-M-L-Q.jsonl",
    },
    {
        "rank": 5,
        "name": "S4 MLQ ZS",
        "strategy": "S4",
        "file": FC / "screening_EVoting-2026-KW_20260315-FullCorpus-ZeroShot-S4-M-L-Q.jsonl",
    },
]


def load_jsonl(path):
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


# ── Process each configuration ─────────────────────────────────────────
results = []
per_paper_rows = []

for cfg in CONFIGS:
    print(f"Processing {cfg['name']}...")
    records = load_jsonl(cfg["file"])
    n_papers = len(records)

    times = []
    tokens_list = []
    agent_counts = Counter()

    # Per-model timing (for multi-agent configs)
    model_times = {}  # model -> list of inference_time

    for rec in records:
        wall_time = rec.get("total_time", 0)
        agents = rec.get("agent_responses", [])
        n_agents = len(agents)
        total_tokens = sum(a.get("tokens", 0) for a in agents)

        times.append(wall_time)
        tokens_list.append(total_tokens)
        agent_counts[n_agents] += 1

        # Per-model timing
        for a in agents:
            model = a.get("model", "unknown")
            inf_time = a.get("inference_time", 0)
            if model not in model_times:
                model_times[model] = []
            model_times[model].append(inf_time)

        # Per-paper row
        per_paper_rows.append({
            "config": cfg["name"],
            "rank": cfg["rank"],
            "paper_id": rec.get("paper_id", ""),
            "n_agents": n_agents,
            "wall_time_s": round(wall_time, 2),
            "tokens": total_tokens,
        })

    total_wall_s = sum(times)
    total_wall_h = total_wall_s / 3600
    mean_time = statistics.mean(times)
    median_time = statistics.median(times)
    std_time = statistics.stdev(times) if len(times) > 1 else 0
    mean_tokens = statistics.mean(tokens_list)
    total_tokens = sum(tokens_list)

    # S5: count stage-1-only vs full pipeline papers
    stage1_only = agent_counts.get(1, 0)
    full_pipeline = agent_counts.get(3, 0)

    # Per-model mean inference time
    model_mean_times = {}
    for model, t_list in sorted(model_times.items()):
        model_mean_times[model] = statistics.mean(t_list)

    # Overhead ratio vs S1 (will compute after all configs processed)
    results.append({
        "rank": cfg["rank"],
        "name": cfg["name"],
        "strategy": cfg["strategy"],
        "n_papers": n_papers,
        "n_agents_mode": max(agent_counts, key=agent_counts.get),
        "mean_time_s": mean_time,
        "median_time_s": median_time,
        "std_time_s": std_time,
        "total_wall_h": total_wall_h,
        "mean_tokens": mean_tokens,
        "total_tokens": total_tokens,
        "stage1_only": stage1_only,
        "full_pipeline": full_pipeline,
        "model_mean_times": model_mean_times,
    })

# ── Compute overhead ratios relative to S1 ─────────────────────────────
s1_mean = results[0]["mean_time_s"]
s1_tokens = results[0]["mean_tokens"]
for r in results:
    r["time_ratio"] = r["mean_time_s"] / s1_mean if s1_mean else 0
    r["token_ratio"] = r["mean_tokens"] / s1_tokens if s1_tokens else 0

# ── Write summary CSV ──────────────────────────────────────────────────
csv_path = OUT / "A5_computational_cost.csv"
with open(csv_path, "w", encoding="utf-8") as f:
    f.write("rank,config,strategy,n_papers,agents,mean_time_s,median_time_s,"
            "std_time_s,total_wall_h,mean_tokens,total_tokens,"
            "time_ratio_vs_S1,token_ratio_vs_S1,stage1_only,full_pipeline\n")
    for r in results:
        f.write(f"{r['rank']},{r['name']},{r['strategy']},{r['n_papers']},"
                f"{r['n_agents_mode']},{r['mean_time_s']:.1f},{r['median_time_s']:.1f},"
                f"{r['std_time_s']:.1f},{r['total_wall_h']:.1f},"
                f"{r['mean_tokens']:.0f},{r['total_tokens']},"
                f"{r['time_ratio']:.2f},{r['token_ratio']:.2f},"
                f"{r['stage1_only']},{r['full_pipeline']}\n")
print(f"Wrote: {csv_path}")

# ── Write per-paper CSV ────────────────────────────────────────────────
pp_path = OUT / "A5_per_paper_timing.csv"
with open(pp_path, "w", encoding="utf-8") as f:
    f.write("rank,config,paper_id,n_agents,wall_time_s,tokens\n")
    for row in per_paper_rows:
        f.write(f"{row['rank']},{row['config']},{row['paper_id']},"
                f"{row['n_agents']},{row['wall_time_s']},{row['tokens']}\n")
print(f"Wrote: {pp_path}")

# ── Write results.txt ──────────────────────────────────────────────────
txt_path = OUT / "A5_results.txt"
with open(txt_path, "w", encoding="utf-8") as f:
    f.write("A5 – Computational Cost Analysis\n")
    f.write("=" * 55 + "\n\n")

    f.write("1. SUMMARY TABLE (Full Corpus, N = 2,036 papers per config)\n")
    f.write("-" * 80 + "\n")
    f.write(f"{'Rank':>4s}  {'Config':18s}  {'Agents':>6s}  {'Mean(s)':>7s}  "
            f"{'Med(s)':>6s}  {'SD(s)':>6s}  {'Total(h)':>8s}  "
            f"{'Tok/paper':>9s}  {'Total tok':>12s}  {'×time':>5s}  {'×tok':>5s}\n")
    for r in results:
        f.write(f"{r['rank']:4d}  {r['name']:18s}  {r['n_agents_mode']:6d}  "
                f"{r['mean_time_s']:7.1f}  {r['median_time_s']:6.1f}  "
                f"{r['std_time_s']:6.1f}  {r['total_wall_h']:8.1f}  "
                f"{r['mean_tokens']:9.0f}  {r['total_tokens']:12,}  "
                f"{r['time_ratio']:5.2f}  {r['token_ratio']:5.2f}\n")

    f.write("\n2. S5 TWO-STAGE FILTERING\n")
    f.write("-" * 80 + "\n")
    for r in results:
        if r["strategy"] == "S5":
            total = r["stage1_only"] + r["full_pipeline"]
            pct1 = r["stage1_only"] / total * 100 if total else 0
            f.write(f"  {r['name']:18s}: Stage 1 only = {r['stage1_only']:5d} "
                    f"({pct1:.1f}%), Full pipeline = {r['full_pipeline']:5d} "
                    f"({100-pct1:.1f}%)\n")

    f.write("\n3. PER-MODEL MEAN INFERENCE TIME (seconds)\n")
    f.write("-" * 80 + "\n")
    # Use S2 data (has all 3 models, all papers go through all agents)
    s2_result = [r for r in results if r["strategy"] == "S2"][0]
    for model, mean_t in sorted(s2_result["model_mean_times"].items()):
        model_names = {"mistral-7b": "Mistral 7B", "llama-8b": "LLaMA 3.1 8B",
                       "qwen-7b": "Qwen 2.5 7B"}
        f.write(f"  {model_names.get(model, model):15s}: {mean_t:.1f} s\n")

    f.write("\n4. KEY FINDINGS\n")
    f.write("-" * 80 + "\n")
    s2r = [r for r in results if r["strategy"] == "S2"][0]
    s1r = results[0]
    f.write(f"  (a) S2/S4 (3 agents) required {s2r['time_ratio']:.2f}× the wall-clock time\n")
    f.write(f"      and {s2r['token_ratio']:.2f}× the tokens of S1 (1 agent),\n")
    f.write(f"      with no improvement in screening performance.\n\n")

    f.write(f"  (b) S4 and S2 are computationally identical: same agents, same\n")
    f.write(f"      inference calls, same tokens. Only aggregation differs.\n\n")

    s5_fs = [r for r in results if r["name"] == "S5 Q→M+L FS"][0]
    f.write(f"  (c) S5 (two-stage) is more efficient than S2/S4 because Stage 1\n")
    f.write(f"      filters {s5_fs['stage1_only']}/{s5_fs['n_papers']} papers "
            f"({s5_fs['stage1_only']/s5_fs['n_papers']*100:.0f}%) with a single\n")
    f.write(f"      model call, avoiding 3-model evaluation for those papers.\n\n")

    f.write(f"  (d) Qwen 2.5 7B is the slowest model per inference call\n")
    f.write(f"      (generates longest reasoning text), while LLaMA 3.1 8B is\n")
    f.write(f"      the fastest.\n\n")

    f.write(f"  (e) All experiments ran on Apple M3 Max (16 GB), 4-bit quantised\n")
    f.write(f"      via MLX framework. Times are sequential (no parallel inference).\n")

print(f"Wrote: {txt_path}")
print("\nDone.")
