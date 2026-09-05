# AI Finance Controller: Execution Walkthrough & Submission Summary

## Overview

The **AI Finance Controller** is an auditable, high-throughput financial reconciliation agent built for **Razorpay's AI Buildathon (Track 04: AI Finance Controller)**.

The core thesis of this project is:
> **Verification capacity, not generation speed, is the bottleneck.**

Our solution operates across multi-source financial datasets (**Razorpay Gateway API exports**, **Bank Statement feeds**, and **Internal ERP Sales Ledgers**) to close the finance-ops loop across synthetic batches, reporting an **honest match rate**, **100.00% verified precision**, and a **transparent line-by-line exception list**.

---

## 1. End-to-End Pipeline Execution Scorecard (50-Record Batch)

Below is the verified output from running the main reconciliation pipeline (`uv run main.py`):

```
======================================================================
   STARTING RECONCILIATION PIPELINE (Batch: batch_50, Size: 50 Records)
======================================================================

[STAGE 1/5] Ingesting Multi-Source Records...
  ✓ Ingested 50 records into 'reconciliation.db' across GATEWAY, BANK, and LEDGER sources.

[STAGE 2/5] Running Pass 1: ExactMatcher (Deterministic Engine)...
  ✓ Pass 1 Exact Matches      : 14 pairs
  ✓ Pass 1 Exact Triplets     : 3 triplets
  ✓ Stage Total Records Matched: 37/50 (74.0%)
  ✓ Remaining Unmatched        : 13 records

[STAGE 3/5] Running Pass 2: ClusteringEngine (Categorical & DBSCAN)...
  ✓ Systemic Clusters Formed  : 2 clusters (8 records)
  ✓ Isolated Singletons        : 5 records

[STAGE 4/5] Running Pass 3: HypothesisEngine (Groq API Pattern Discovery)...
  🤖 [GROQ LLM CALL] Requesting pattern analysis for CLUST_SETTLEMENT_01...
  🤖 [GROQ LLM RESPONSE]:
  {
      "hypothesis_type": "PERCENTAGE_FEE",
      "parameters": { "fee_percent": 0.02 },
      "reasoning": "The discrepancy between gateway total (3750.0) and bank net (3675.0) equals 2% batch fee applied to settlement."
  }
  🤖 [GROQ LLM CALL] Requesting pattern analysis for CLUST_FEE_02...
  🤖 [GROQ LLM RESPONSE]:
  {
      "hypothesis_type": "PERCENTAGE_FEE",
      "parameters": { "fee_percent": 0.02, "flat_fee": 3.0 },
      "reasoning": "Deducting 2% gateway fee plus ₹3 flat GST explains the variance between gateway gross and bank net credit."
  }
  ✓ Systemic Hypotheses Proven : 2/2 tested
  ✓ Layer 3 Additional Matches : 8 records
  ✓ Singletons Classified     : 5 records

[STAGE 5/5] Generating Evaluation Scorecard & Ground-Truth Accuracy Audit...
===========================================================================
        RECONCILIATION EVALUATION SCORECARD (batch_50)
===========================================================================
  Total Ingested Batch Records  : 50
  Successfully Matched Records  : 45
  Flagged Exception Records     : 5
  Overall Batch Match Rate      : 90.00%
---------------------------------------------------------------------------
  ACCURACY & AUDIT METRICS:
  - Match Precision (Target 100%): 100.00% (False Positives: 0)
  - Match Recall (Ground Truth)  : 100.00% (45/45 GT records)
  - Exception Categorization Acc : 100.00%
---------------------------------------------------------------------------
  HONEST EXCEPTION SUMMARY:
    * DUPLICATE_ENTRY          : 2 records
    * TRUE_SINGLETON           : 3 records
---------------------------------------------------------------------------
  UNMATCHED EXCEPTION TRANSACTIONS (LINE-BY-LINE DETAIL):
  RECORD ID  | SOURCE   | AMOUNT (₹)   | REF / EXT ID         | CATEGORY
  -----------------------------------------------------------------------
  REC_0046   | LEDGER   | ₹10324.18    | REF_ORPHAN_01        | DUPLICATE_ENTRY
  REC_0047   | BANK     | ₹6986.41     | REF_ORPHAN_02        | TRUE_SINGLETON
  REC_0048   | GATEWAY  | ₹35894.61    | REF_ORPHAN_03        | DUPLICATE_ENTRY
  REC_0049   | LEDGER   | ₹17471.53    | REF_ORPHAN_04        | TRUE_SINGLETON
  REC_0050   | LEDGER   | ₹4500.02     | REF_ORPHAN_05        | TRUE_SINGLETON
===========================================================================

======================================================================
        SUSTAINABILITY & CARBON EMISSION AUDIT (CodeCarbon)
======================================================================
  Target Workload Records    : 50 transactions
  Region / Grid Energy ISO   : IND
  Total Carbon Emissions     : 121.2945 mg CO2eq (0.00012129 kg)
  Emissions Per Transaction  : 2.4259 mg CO2eq / tx
  Total Energy Consumption   : 0.00017001 kWh
  CodeCarbon Tracker Status  : ACTIVE (Audited)
======================================================================
```

---

## 2. Unmatched Exception Transactions (Detailed View)

The 5 unmatched records were transparently categorized and displayed:

| Record ID | Source | Amount (₹) | Reference / External ID | Flagged Category | Root Cause Explanation |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `REC_0046` | `LEDGER` | ₹10,324.18 | `REF_ORPHAN_01` | `DUPLICATE_ENTRY` | Accidental duplicate export retry in ERP ledger |
| `REC_0047` | `BANK` | ₹6,986.41 | `REF_ORPHAN_02` | `TRUE_SINGLETON` | Unmatched orphan bank credit without gateway record |
| `REC_0048` | `GATEWAY` | ₹35,894.61 | `REF_ORPHAN_03` | `DUPLICATE_ENTRY` | Duplicate payment webhook entry |
| `REC_0049` | `LEDGER` | ₹17,471.53 | `REF_ORPHAN_04` | `TRUE_SINGLETON` | Unsettled invoice entry in merchant ledger |
| `REC_0050` | `LEDGER` | ₹4,500.02 | `REF_ORPHAN_05` | `TRUE_SINGLETON` | Unassigned journal entry in merchant ledger |

---

## 3. Architecture & Verification Mechanics

```
┌────────────────────────────────────────────────────────┐
│             MULTI-SOURCE DATA INGESTION                │
│  Standardized Gateway, Bank, and ERP Ledger Records    │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│           PASS 1: EXACT MATCHER (Deterministic)        │
│  1:1 Key-Amount & 1:1:1 Triplets | 100% Precision      │
└───────────────────────────┬────────────────────────────┘
                            │ (37/50 Records Resolved)
                            ▼
┌────────────────────────────────────────────────────────┐
│           PASS 2: CLUSTERING ENGINE (Categorical)      │
│  Groups unmatched items into fee & settlement clusters │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│     PASS 3: HYPOTHESIS ENGINE (Groq LLM Powered)      │
│  Groq API (openai/gpt-oss-120b) analyzes diffs         │
│  Proves rules deterministically (8/50 Records Resolved)│
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│        HUMAN-IN-THE-LOOP & INTERROGATION CHAT         │
│  Zero-hallucination Q&A from SQLite audit_log facts    │
└───────────────────────────┬────────────────────────────┘
```

### Key Technical Safeguards
1. **Zero Execution Authority for LLMs**: The LLM acts as a hypothesis proposer and classifier. Every match must pass deterministic zero-delta verification against database records.
2. **Master Append-Only Audit Log ([src/db.py](file:///home/arnav-gupta/Projects/ai-finance-controller/src/db.py))**: Every state change writes to `audit_log` in SQLite before updating state tables.
3. **Groq API Integration ([src/hypothesis_engine.py](file:///home/arnav-gupta/Projects/ai-finance-controller/src/hypothesis_engine.py))**: Uses `openai/gpt-oss-120b` to analyze residual field-level diffs and propose typed JSON hypothesis structs.

---

## 4. How to Run & Verify

### A. Run End-to-End Pipeline
```bash
uv run main.py
```

### B. Launch Interactive Human-in-the-Loop Terminal
```bash
PYTHONPATH=. uv run python src/cli.py
```

### C. Re-Generate Synthetic Dataset (50 or 200 Records)
```bash
PYTHONPATH=. uv run python src/data_generator.py
```
