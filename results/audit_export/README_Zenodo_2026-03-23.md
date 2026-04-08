# Blockchain-Verified Audit Trail: Automated Title-Abstract Screening

## Dataset Description

This dataset contains the complete blockchain-verified audit log from the title-abstract screening phase of a systematic review on blockchain-based electronic voting systems. The screening was conducted using **PaSSER-SR** (A Web Platform for AI-Assisted Title-Abstract Screening), combining human expert decisions with LLM-based screening across multiple strategies and models.

## Related Work

This dataset accompanies a manuscript submitted for peer review:

Radeva, I.; Popchev, I.; Doukovska, L.; Noncheva, T. *Comparing Single-Agent and Multi-Agent Strategies in LLM-Based Title-Abstract Screening.* Electronics (under review), 2026.

The dataset is self-contained and independently verifiable regardless of the publication status of the manuscript.

## Contents

| File | Description |
|------|-------------|
| `EVoting-2026-KW_final_corpus_*.json` | Complete audit export (Sections A-F below) |
| `EVoting-2026-KW_final_corpus_*.json.ots` | OpenTimestamps proof anchored to the Bitcoin blockchain |
| `full_text_review_list.csv` | 949 papers selected for full-text review (paper_id, title, DOI, confidence) |
| `README_Zenodo_2026-03-23.md` | This file |

## Export Structure (JSON)

### Section A: Human Decisions (`human_decisions`)
404 screening decisions by three accounts: Screener A (200, primary screener + resolver for 50 disagreements), Screener B (200, independent primary screener), and Admin (4, blockchain administrator test screening). Each record includes decision (INCLUDE/EXCLUDE/UNCERTAIN), confidence level, criteria applied, reasoning, and Antelope blockchain transaction ID. Inter-rater agreement: Cohen's kappa = 0.515.

### Section B: Resolutions (`resolutions`)
50 disagreement resolutions (34 EXCLUDE, 9 INCLUDE, 7 UNCERTAIN), with resolver account, final decision, and resolution reason.

### Section C: Gold Standard LLM Evaluation (`llm_gs_decisions`)
5,492 decisions across 29 configurations (strategies S1–S5, 4 models, zero-shot and few-shot). Grouped by `job_id`. Each decision includes model output, confidence score, criteria cited, and blockchain transaction ID.

### Section D: Full Corpus LLM Screening (`llm_fc_decisions`)
12,216 decisions across 6 configurations × 2,036 papers (5 reported in paper + 1 test run not reported). Grouped by `job_id`. Configurations: S1/Qwen 7B/few-shot, S2/MLQ/zero-shot, S4/MLQ/zero-shot, S5/Q→L+M/few-shot, S5/L→M+Q/few-shot, S5/M→L+Q/zero-shot (test run).

### Section E: LLM Job Metadata (`llm_jobs`)
48 LLM screening jobs with strategy, models, prompt mode, paper count, timestamps, and completion status.

### Section F: Final Inclusion List (`final_inclusion_list`)
Papers selected for full-text review based on the best-performing configuration (S1 SINGLE / Qwen 2.5 7B / few-shot). This list constitutes the input for the subsequent full-text screening phase. A CSV extract (`full_text_review_list.csv`) with paper_id, title, DOI, and confidence scores is provided for convenience (949 papers; 853 with DOI, 96 without).

### Integrity (`audit`)
Merkle root (SHA-256), 18,162 leaves, file hash, and Antelope blockchain transaction ID (`807b730...549af`).

## Three-Tier Verification Model

### Tier 1: Operational Logging (Antelope Blockchain)
Each screening decision was recorded as an immutable transaction on a private Antelope blockchain via the `sraudit` smart contract. Transaction IDs are embedded in the individual records.

### Tier 2: Temporal Anchoring (OpenTimestamps + Bitcoin)
A Merkle tree was constructed from all decision records (human + LLM). The Merkle root and file hash were recorded on the Antelope blockchain, then the file hash was submitted to OpenTimestamps for anchoring to the Bitcoin blockchain.

### Tier 3: Archival Publication (Zenodo)
This deposit constitutes the third tier, providing persistent DOI-based access for independent verification.

## Verification Instructions

### Step 1: Verify file integrity
```bash
shasum -a 256 EVoting-2026-KW_final_corpus_*.json
# Compare output with the file_hash in the JSON audit section
```

### Step 2: Verify Bitcoin timestamp
```bash
pip install opentimestamps-client
ots verify EVoting-2026-KW_final_corpus_*.json.ots
```

### Step 3: Reconstruct Merkle root
The Merkle tree was built from all records (human_decisions + resolutions + llm_gs_decisions + llm_fc_decisions) using SHA-256 bottom-up pairwise concatenation with leaf duplication for odd counts. Each leaf is the SHA-256 hash of the JSON-serialized record (with sorted keys). The reconstructed root should match the `audit.merkle_root` field.

## Technical Details

- **Platform**: PaSSER-SR v4 (A Web Platform for AI-Assisted Title-Abstract Screening)
- **Blockchain**: Antelope (EOSIO-compatible), private instance
- **Smart contract**: `sraudit` v2.0 (multi-project support)
- **Hash algorithm**: SHA-256
- **LLM models**: Mistral 7B v0.3, LLaMA 3.1 8B, Qwen 2.5 7B, Granite 3.3 8B (4-bit quantised, Apple MLX)
- **Screening strategies**: S1 (single-agent), S2 (majority voting), S3 (recall-focused OR), S4 (confidence-weighted), S5 (two-stage debate)
- **Gold standard**: 200 papers (190 evaluation + 10 calibration)
- **Full corpus**: 2,036 papers

## License

CC BY 4.0

## Authors

- Irina Radeva  - Institute of Information and Communication Technologies, Bulgarian Academy of Sciences (IICT-BAS), Intelligent Systems Department, Sofia, Bulgaria; Trakia University, Faculty of Digital and Green Technologies, Stara Zagora, Bulgaria
- Ivan Popchev  - Bulgarian Academy of Sciences, Sofia, Bulgaria
- Lyubka Doukovska  - Institute of Information and Communication Technologies, Bulgarian Academy of Sciences (IICT-BAS), Intelligent Systems Department, Sofia, Bulgaria; Trakia University, Faculty of Digital and Green Technologies, Stara Zagora, Bulgaria
- Teodora Noncheva  - Institute of Information and Communication Technologies, Bulgarian Academy of Sciences (IICT-BAS), Intelligent Systems Department, Sofia, Bulgaria; Trakia University, Faculty of Digital and Green Technologies, Stara Zagora, Bulgaria
