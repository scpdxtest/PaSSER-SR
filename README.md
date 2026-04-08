# PaSSER-SR: A Web Platform for AI-Assisted Title-Abstract Screening

Supplementary material for:

> Radeva, I.; Popchev, I.; Doukovska, L.; Noncheva, T. *Comparing Single-Agent and Multi-Agent Strategies in LLM-Based Title-Abstract Screening.* Electronics (under review), 2026.

PaSSER-SR is a web-based platform for AI-assisted title-abstract screening that integrates human expert decisions with LLM-based automated screening and blockchain audit trails. This repository contains the platform source code, the input corpus, screening results, and evaluation data reported in the paper.

## Repository Structure

```
passer-sr/
+-- src/                          # React frontend (v18)
|   +-- component/
|   |   +-- Screening.js          # Human screening module
|   |   +-- LLMScreening.js       # LLM screening interface
|   |   +-- AdminDashboard.js     # Dashboard with audit trail
|   |   +-- SelectModel.js        # Model and strategy configuration
|   |   +-- TestWharf.js          # Anchor wallet (blockchain login)
|   |   +-- BCEndpoints.js        # Blockchain endpoint checker
|   |   +-- configuration.json    # Endpoint configuration
|   +-- constants/
|       +-- screeningCriteria.js   # IC1-IC5 and EC1-EC6 definitions
+-- scripts/                      # Python backend and utilities
|   +-- screening_api.py          # FastAPI backend - human screening (port 9901)
|   +-- llm_screening_api.py      # FastAPI backend - LLM screening (port 9902)
|   +-- mlx_screening_engine.py   # Apple MLX inference engine (4-bit quantised)
|   +-- evaluate.py               # Evaluation metrics (Recall, Precision, F1, WSS@95)
|   +-- screening_criteria_constants.py  # Shared IC/EC criteria
|   +-- arxiv_search.py           # ArXiv corpus search
|   +-- semantic_search.py        # Semantic Scholar corpus search
|   +-- openalex_search.py        # OpenAlex corpus search
|   +-- core_search.py            # CORE corpus search
|   +-- mdpi_search.py            # MDPI corpus search
|   +-- mdpi_bibtex_converter.py  # MDPI BibTeX-to-JSON converter
|   +-- deduplicate.py            # Cross-source deduplication
|   +-- filter_electoral.py       # Domain-specific keyword filtering
|   +-- gold_standard_sampling.py # Stratified gold-standard sampling
|   +-- import_corpus.py          # Import corpus into MongoDB
|   +-- import_gold_standard.py   # Import gold standard into MongoDB
|   +-- import_users.py           # Import user accounts
|   +-- users_template.json       # User configuration template
|   +-- A1_agreed_vs_disputed_FIXED.py    # Agreed vs. disputed GS subset analysis
|   +-- A2_A3_mcnemar_power_FIXED.py      # McNemar pairwise test + power analysis
|   +-- A4_confidence_distribution.py     # Confidence distribution analysis (S2, S4)
|   +-- A5_computational_cost.py          # Computational cost (wall-clock, tokens)
|   +-- A6_granite_ablation.py            # Granite ablation (MLG vs. MLQ)
+-- blockchain/                   # Antelope smart contract
|   +-- sraudit.cpp               # Audit contract source (C++, v2.1)
|   +-- sraudit.abi               # Contract ABI
+-- Initial import/               # Input data
|   +-- *.bib                     # BibTeX exports from academic databases
|   +-- results/                  # First search iteration (pre-keyword filtering)
|   +-- results_KW/               # Final corpus after keyword-based filtering
|       +-- filtered_corpus.json  # 2,036 papers (deduplicated, filtered)
|       +-- gold_standard/        # 200-paper gold standard subset
+-- results/                      # Screening results (reported in paper)
|   +-- human_evaluation/         # Human screening (200 papers, anonymised)
|   +-- gold_standard_evaluation/ # LLM evaluation on gold standard (25 configs)
|   |   +-- strategy_comparison_*.json/xlsx  # Recall, Precision, F1, WSS@95
|   |   +-- error_analysis_protocol_25configs.xlsx
|   |   +-- error_analysis/       # Per-config error analysis (JSON)
|   +-- full_corpus/              # Full corpus screening (2,036 papers)
|   |   +-- job_metrics/          # Per-job metrics (JSON + XLSX, 6 configs)
|   |   +-- error_analysis/       # Per-job error analysis (JSON)
|   +-- full_text_review_list.csv # 949 papers selected for full-text review
|   +-- audit_export/             # Blockchain audit export + timestamp proof
|   |   +-- EVoting-2026-KW_final_corpus_20260317_134310.json
|   |   +-- EVoting-2026-KW_final_corpus_20260317_134310.json.ots
|   |   +-- full_text_review_list.csv
|   |   +-- README_Zenodo_2026-03-23.md
|   +-- Additional_analysis/      # Additional analyses (CSV outputs)
|       +-- A1_agreed_vs_disputed_results.csv
|       +-- A2_A3_mcnemar_pairwise.csv
|       +-- A4_confidence_distribution.csv
|       +-- A4_s4_vs_s2_comparison.csv
|       +-- A5_computational_cost.csv
|       +-- A5_per_paper_timing.csv
|       +-- A6_granite_ablation.csv
+-- .env.example                  # Environment variable template
```

## Study Overview

The paper evaluates five LLM-based screening strategies for title-abstract screening in a systematic review on blockchain-based electronic voting systems.

**Screening strategies:**

- S1 (Single-Agent) --one model screens independently
- S2 (Majority Voting) --three models vote, majority decides
- S3 (Recall-Focused OR) --any INCLUDE from three models triggers inclusion
- S4 (Confidence-Weighted) --weighted average of three model confidence scores
- S5 (Two-Stage Filtering) --fast-filter model + two-model majority voting panel

**LLM models (4-bit quantised, Apple MLX):**

- Mistral 7B v0.3
- LLaMA 3.1 8B
- Qwen 2.5 7B
- IBM Granite 3.3 8B

**Gold standard:** 200 papers screened independently by two human reviewers (Cohen's kappa = 0.515), with disagreement resolution.

**Best configuration:** S1 / Qwen 2.5 7B / few-shot --Recall 100%, Precision 70.4%, F1 82.6%, WSS@95 43.4%.

**Full corpus result:** 949 of 2,036 papers selected for full-text review.

## Blockchain Audit Trail

Every screening decision (human and LLM) is recorded as an immutable transaction on a private Antelope blockchain via the `sraudit` smart contract (v2.1). The complete audit export, Merkle root, and OpenTimestamps proof anchored to the Bitcoin blockchain are deposited on Zenodo: [https://doi.org/10.5281/zenodo.19182242](https://doi.org/10.5281/zenodo.19182242).

The smart contract (`blockchain/sraudit.cpp`) implements the following on-chain actions: `logdecision`, `logres`, `logimport`, `logexport`, `logllmdec`, `logllmjob`, and `logaudit`.

## Additional Analyses

Six additional analysis scripts are provided. Each script reads data from the audit export and gold standard evaluation results. All outputs are saved in `results/Additional_analysis/`.

| Script | Section | Description |
|--------|---------|-------------|
| `A1_agreed_vs_disputed_FIXED.py` | 4.5 | Compares screening performance on agreed vs. disputed Gold Standard subsets (150 agreed, 50 disputed). |
| `A2_A3_mcnemar_power_FIXED.py` | 4.6 | Pairwise McNemar's exact test between the top five configurations with post-hoc power analysis. |
| `A4_confidence_distribution.py` | 4.2 | Analyses confidence score distributions across models for S2 and S4 strategies. |
| `A5_computational_cost.py` | 5.1 | Computes wall-clock time, token counts, and per-paper timing for the top five configurations. |
| `A6_granite_ablation.py` | 5.1 | Ablation comparing ensembles with Granite (MLG) vs. ensembles with Qwen replacing Granite (MLQ). |

Running the analyses:

```bash
cd scripts
python A1_agreed_vs_disputed_FIXED.py
python A2_A3_mcnemar_power_FIXED.py
python A4_confidence_distribution.py
python A5_computational_cost.py
python A6_granite_ablation.py
```

All scripts require the audit export JSON in `results/audit_export/` and the gold standard evaluation data in `results/gold_standard_evaluation/`.

## Prerequisites

- Node.js >= 16
- Python >= 3.10
- MongoDB
- Antelope blockchain node (optional, for audit trail)
- [Anchor Wallet](https://www.greymass.com/anchor) (for blockchain login)
- Apple Silicon Mac (for MLX-based LLM inference)

## Setup

### 1. Frontend

```bash
npm install
npm start
```

### 2. Environment Variables

```bash
cp .env.example .env
```

Edit `.env` with your MongoDB URI, blockchain endpoint, and private key.

### 3. Configuration

Edit `src/component/configuration.json` with your endpoint URLs for Ollama, ChromaDB, blockchain nodes, and IPFS.

### 4. Backend APIs

```bash
cd scripts

# Human Screening API (port 9901)
python screening_api.py --port 9901

# LLM Screening API (port 9902)
python llm_screening_api.py --port 9902
```

### 5. Data Import

```bash
cd scripts

# Import users
python import_users.py --users users_template.json

# Import corpus
python import_corpus.py --input ../Initial\ import/results_KW/filtered_corpus.json --project <PROJECT_ID>

# Import gold standard
python import_gold_standard.py --input ../Initial\ import/results_KW/gold_standard/gold_standard_200.json --project <PROJECT_ID>
```

### 6. Blockchain Contract

```bash
cd blockchain
# Compile
cdt-cpp -abigen -o sraudit.wasm sraudit.cpp
# Deploy
cleos -u http://<BLOCKCHAIN_ENDPOINT> set contract sraudit ./ sraudit.wasm sraudit.abi
```

## Evaluation

```bash
cd scripts
python evaluate.py --project <PROJECT_ID> --output results.json
```

## Screening Criteria

**Inclusion (IC1-IC5):** blockchain-based system for electoral processes, with empirical evaluation, security analysis, and implementation.

**Exclusion (EC1-EC6):** no blockchain, non-electoral domain, opinion/survey without methodology, duplicate, non-English, inaccessible full text.

Full criteria definitions are in `scripts/screening_criteria_constants.py` and `src/constants/screeningCriteria.js`.

## Data Availability

- **Source code and results:** this repository
- **Full audit export (18,162 records) + OpenTimestamps proof:** Zenodo [https://doi.org/10.5281/zenodo.19182242](https://doi.org/10.5281/zenodo.19182242)
- **Full-text review list (949 papers with DOI):** `results/full_text_review_list.csv` and Zenodo deposit