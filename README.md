# AI Finance Controller — Auditable Multi-Source Reconciliation Agent

> **Razorpay AI Buildathon (Track 04: AI Finance Controller)**  
> *"Verification capacity, not generation speed, is the bottleneck."*

---

## Executive Summary

The **AI Finance Controller** is an auditable, high-precision financial reconciliation system designed to close the finance-ops loop across multi-source financial feeds (**Razorpay Gateway Exports**, **Bank Statement Feeds**, and **Merchant ERP Sales Ledgers**). 

Instead of delegating execution authority to LLMs, our architecture treats LLMs strictly as **pattern discovery hypothesis proposers**. Every financial match must pass deterministic zero-delta database verification, achieving an **honest match rate**, **100.00% verified precision (0 false positives)**, and a **transparent line-by-line exception list**.

---

## System Architecture & Pipeline Flow

```
+-----------------------------------------------------------------------+
|                    MULTI-SOURCE DATA INGESTION                        |
|  Ingests GATEWAY (Razorpay), BANK Feeds, and ERP LEDGER Transactions   |
+-----------------------------------┬-----------------------------------+
                                    |
                                    v
+-----------------------------------------------------------------------+
|             PASS 1: EXACT MATCHER (Deterministic Engine)             |
|  Resolves 1:1 Key-Amount Matches & 1:1:1 Triplets | 100% Precision    |
+-----------------------------------┬-----------------------------------+
                                    | (Unmatched Records Passed Forward)
                                    v
+-----------------------------------------------------------------------+
|             PASS 2: CLUSTERING ENGINE (Categorical & DBSCAN)          |
|  Groups residual unmatched items into systemic settlement clusters    |
+-----------------------------------┬-----------------------------------+
                                    |
                                    v
+-----------------------------------------------------------------------+
|           PASS 3: HYPOTHESIS ENGINE (Groq API Powered LLM)            |
|  Groq API (groq/compound) discovers fee formulas & time offsets       |
|  Proves rules deterministically against SQLite master records         |
+-----------------------------------┬-----------------------------------+
                                    |
                                    v
+-----------------------------------------------------------------------+
|            HUMAN-IN-THE-LOOP & PROACTIVE AGENT CHAT                   |
|  Human approval panel + Zero-hallucination Q&A from audit_log facts   |
+-----------------------------------┬-----------------------------------+
                                    |
                                    v
+-----------------------------------------------------------------------+
|          EVALUATION SCORECARD & CODECARBON SUSTAINABILITY AUDIT       |
|  Precision/Recall metrics, exception table, and CO2eq energy tracking |
+-----------------------------------------------------------------------+
```

---

## Core Features & Technical Safeguards

- **Zero Raw Execution Authority for LLMs**: Every state change writes to an append-only `audit_log` single source of truth in SQLite (`reconciliation.db`) before updating state tables.
- **Sequential Streamlit Dashboard (`app.py`)**: An interactive 6-step wizard featuring batch parameter controls (default **80 data points per run**), layer-by-layer visualizations, Plotly feature space charts, live fee testing sliders, and proactive agent chat.
- **Groq API Rate-Limit Resilience (`src/hypothesis_engine.py`)**: Multi-model candidate fallback (`groq/compound` -> `llama-3.3-70b-versatile` -> `llama-3.1-8b-instant`) to smoothly handle free-tier 429 TPD token limits.
- **CodeCarbon Sustainability Audit (`src/carbon_tracker.py`)**: Real-time energy monitoring tracking power consumption ($kWh$) and carbon footprint ($mg CO_2\text{eq}$ / transaction).
- **Proactive Agent Interrogation Chat**: Zero-hallucination Q&A assistant grounded 100% in factual SQLite audit trail events.

---

## Project Structure

```
ai-finance-controller/
├── app.py                      # Interactive Sequential Streamlit Dashboard
├── main.py                     # Pipeline Execution Entry Point
├── pyproject.toml              # UV Package & Dependency Manifest
├── README.md                   # Technical Documentation & User Guide
├── .env                        # Environment Configuration (GROQ_API_KEY)
├── .streamlit/
│   └── secrets.toml            # TOML Secrets Configuration
├── src/
│   ├── carbon_tracker.py       # CodeCarbon Sustainability & Energy Audit Wrapper
│   ├── cli.py                  # Human-in-the-Loop Terminal CLI & Chat
│   ├── clustering.py           # Pass 2 Categorical & DBSCAN Sub-Clustering Engine
│   ├── data_generator.py       # Multi-Source Synthetic Dataset Generator (50, 80, 200 records)
│   ├── db.py                   # Master SQLite Schema & Atomic AuditLogger
│   ├── evaluator.py            # Accuracy Scorecard & Exception Detail Generator
│   ├── exact_matcher.py        # Pass 1 Deterministic 1:1 & 1:1:1 Triplet Matcher
│   ├── hypothesis_engine.py    # Pass 3 Groq LLM Hypothesis Generator & Prover
│   └── ingest.py               # Raw Record Batch Ingestion Module
├── docs/
│   ├── overview.md             # High-Level Architecture & Technical Specification
│   ├── schema.md               # Relational Database Schema DDL Specification
│   ├── data_generation.md      # Ground-Truth Dataset Generator Specification
│   └── walkthrough.md          # Submission Guide & Evaluation Scorecard Report
└── tests/                      # Automated Pytest Suite (16 Unit & Integration Tests)
    ├── test_carbon_tracker.py
    ├── test_cli.py
    ├── test_clustering.py
    ├── test_data_generator.py
    ├── test_db.py
    ├── test_evaluator.py
    ├── test_exact_matcher.py
    ├── test_hypothesis_engine.py
    └── test_pipeline_e2e.py
```

---

## Installation & Setup

### Prerequisites
- Python 3.13+
- [`uv`](https://github.com/astral-sh/uv) fast Python package manager

### 1. Clone & Install Dependencies
```bash
git clone git@github.com:arnav-engineer/ai-finance-controller.git
cd ai-finance-controller
uv sync
```

### 2. Configure Groq API Key
Add your Groq API key to `.env` or `.streamlit/secrets.toml`:

**In `.env`:**
```env
GROQ_API_KEY=gsk_your_groq_api_key_here
```

**In `.streamlit/secrets.toml`:**
```toml
GROQ_API_KEY = "gsk_your_groq_api_key_here"
```

---

## Execution Modes

### A. Launch Interactive Streamlit Dashboard
```bash
uv run streamlit run app.py
```
Open **`http://localhost:8501`** in your browser.

### B. Run End-to-End Reconciliation Pipeline (CLI)
```bash
uv run main.py
```

### C. Launch Human-in-the-Loop Terminal CLI
```bash
PYTHONPATH=. uv run python src/cli.py
```

### D. Execute Automated Test Suite
```bash
PYTHONPATH=. uv run pytest -v
```

---

## Evaluation Scorecard Output Sample

```
===========================================================================
        RECONCILIATION EVALUATION SCORECARD (batch_80)
===========================================================================
  Total Ingested Batch Records  : 80
  Successfully Matched Records  : 72
  Flagged Exception Records     : 8
  Overall Batch Match Rate      : 90.00%
---------------------------------------------------------------------------
  ACCURACY & AUDIT METRICS:
  - Match Precision (Target 100%): 100.00% (False Positives: 0)
  - Match Recall (Ground Truth)  : 100.00% (72/72 GT records)
  - Exception Categorization Acc : 100.00%
---------------------------------------------------------------------------
  SUSTAINABILITY & CARBON EMISSION AUDIT (CodeCarbon)
---------------------------------------------------------------------------
  Region / Grid Energy ISO      : IND
  Total Carbon Emissions        : 121.2945 mg CO2eq
  Emissions Per Transaction     : 2.4259 mg CO2eq / tx
  Total Energy Consumption      : 0.00017001 kWh
===========================================================================
```

---

## License
Built for **Razorpay's AI Buildathon Track 04 (AI Finance Controller)**. Distributed under the MIT License.
