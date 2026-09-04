# Synthetic Data Generation Specification

This document explains the architecture, statistical distribution, schema structures, and seeded test scenarios for the **200-record synthetic financial batch** (`data_batch_200.json`) used by the **AI Finance Controller** reconciliation engine.

---

## 1. Overview & Generation Philosophy

To evaluate an automated reconciliation agent honestly, **cherry-picked single-row matches prove nothing**. The synthetic data generator (`src/data_generator.py`) creates multi-source batches that emulate real-world Indian payment gateway reconciliation (specifically Razorpay API exports, bank account statements, and merchant ERP ledgers).

### Core Principles
1. **Multi-Source Diversity**: Generates transactions across 3 distinct financial systems:
   - **GATEWAY**: Razorpay API export schema (`pay_xxx`, `order_xxx`, fee/tax breakdowns).
   - **BANK**: Bank statement credit/debit feeds (UTR numbers, bank narrations, net settlement credits).
   - **LEDGER**: Internal merchant ERP accounts (`LEDGER_xxxx`, double-entry sales credits).
2. **Seeded Systemic Patterns**: Includes realistic systemic distortions (e.g., UTC vs IST timezone shifts, percentage gateway fee deductions, batch settlement payouts) to test Layer 3 pattern discovery.
3. **Strict Ground-Truth Isolation**: Each generated record carries hidden ground-truth evaluation tags (`gt_match_id`, `gt_exception_type`). These tags are populated during generation but **never read by the matching pipeline**. They are consumed exclusively by the evaluation harness to calculate true precision, recall, and exception match rates.

---

## 2. Batch Composition & Statistical Distribution

The 200-record synthetic batch (`batch_200`) is distributed as follows:

```
Total Generated Records: 200
  ├── GATEWAY: 93 records
  ├── BANK: 88 records
  └── LEDGER: 19 records

Ground-Truth Summary:
  ├── 73 Ground-Truth Match Groups (135 total matching records)
  └── 32 Flagged Exception Records (Edge cases & true singletons)
```

### Detailed Breakdown Table

| Category | Record Count | Source Breakdown | Description / Seeded Pattern |
| :--- | :--- | :--- | :--- |
| **1:1 Happy Path Pair** | 90 records (45 pairs) | 45 GATEWAY, 45 BANK | Exact match on `reference_id` (Order ID) and amount. Timestamps match within 60 seconds. |
| **1:1:1 Triplet Match** | 45 records (15 triplets) | 15 GATEWAY, 15 BANK, 15 LEDGER | Exact 3-way match across Gateway, Bank statement, and Internal ERP Ledger. |
| **Time Offset Cluster** | 12 records (6 pairs) | 6 GATEWAY, 6 BANK | Systemic timezone offset (+5 hours 30 mins / 19,800 seconds, UTC vs IST). |
| **Fee Mismatch Cluster** | 12 records (6 pairs) | 6 GATEWAY, 6 BANK | Bank credit equals Gateway gross minus $2\% \text{ fee} + \text{₹3 GST}$. |
| **Many-to-One Settlement** | 9 records | 8 GATEWAY, 1 BANK | 8 Gateway payment records aggregated into 1 Bank Settlement UTR payout (net of 2% batch fee). |
| **Amount Out-of-Tolerance** | 6 records (3 pairs) | 3 GATEWAY, 3 BANK | Amount mismatch exceeding standard engine tolerance (e.g. off by ₹450). |
| **Missing / Malformed Ref** | 6 records (3 pairs) | 3 GATEWAY, 3 BANK | Bank narration reference ID garbled or missing (`reference_id = NULL`). |
| **Duplicate Payment Entry** | 2 records (1 pair) | 2 GATEWAY | Duplicate payment entry with identical external payment ID (`pay_dup_001`). |
| **True Singletons** | 18 records | 8 GATEWAY, 7 BANK, 3 LEDGER | Unmatched orphan entries (unmatched bank charges, cancelled orders, missing ledger entries). |
| **Total** | **200 records** | **93 GATEWAY, 88 BANK, 19 LEDGER** | Complete test batch. |

---

## 3. Data Source Schemas

### 3.1 `GATEWAY` (Razorpay API Schema)
```json
{
  "record_id": "REC_0001",
  "batch_id": "batch_200",
  "source_type": "GATEWAY",
  "external_id": "pay_a1b2c3d4e5",
  "reference_id": "order_hp_0001",
  "amount": 14500.50,
  "currency": "INR",
  "fee": 290.01,
  "tax": 52.20,
  "timestamp": "2026-09-01T10:05:00+00:00",
  "status": "UNMATCHED",
  "raw_data": {
    "payment_id": "pay_a1b2c3d4e5",
    "order_id": "order_hp_0001",
    "method": "upi",
    "utr": "UTR8849201928",
    "gateway": "Razorpay"
  },
  "gt_match_id": "GT_HAPPY_1to1_001",
  "gt_exception_type": null
}
```

### 3.2 `BANK` (Bank Statement Schema)
```json
{
  "record_id": "REC_0002",
  "batch_id": "batch_200",
  "source_type": "BANK",
  "external_id": "UTR8849201928",
  "reference_id": "order_hp_0001",
  "amount": 14500.50,
  "currency": "INR",
  "fee": 0.0,
  "tax": 0.0,
  "timestamp": "2026-09-01T10:05:32+00:00",
  "status": "UNMATCHED",
  "raw_data": {
    "utr": "UTR8849201928",
    "description": "CMS/RAZORPAY/order_hp_0001/UTR8849201928",
    "bank_name": "HDFC Bank",
    "entry_type": "CREDIT"
  },
  "gt_match_id": "GT_HAPPY_1to1_001",
  "gt_exception_type": null
}
```

### 3.3 `LEDGER` (Internal ERP Schema)
```json
{
  "record_id": "REC_0047",
  "batch_id": "batch_200",
  "source_type": "LEDGER",
  "external_id": "LEDGER_0001",
  "reference_id": "order_triplet_0001",
  "amount": 8920.00,
  "currency": "INR",
  "fee": 0.0,
  "tax": 0.0,
  "timestamp": "2026-09-01T22:00:00+00:00",
  "status": "UNMATCHED",
  "raw_data": {
    "ledger_id": "LEDGER_0001",
    "order_id": "order_triplet_0001",
    "account": "1001-Sales"
  },
  "gt_match_id": "GT_HAPPY_1to1to1_001",
  "gt_exception_type": null
}
```

---

## 4. Seeded Systemic Scenarios

### Scenario A: UTC vs IST Timezone Offset Cluster
- **Pattern**: Bank timestamps are systematically shifted by $+5\text{h } 30\text{m}$ ($19,800\text{ seconds}$) compared to Gateway timestamps due to servers operating in different timezone configs.
- **Target Component**: **Layer 3 Hypothesis Engine** (`TIME_OFFSET` hypothesis template).
- **Target Verification**: Engine detects $100\%$ match rate when applying offset parameters `{"offset_seconds": 19800}` across Cluster `CLUST_TIMEOFFSET`.

### Scenario B: Percentage + Flat Fee Deduction Cluster
- **Pattern**: Merchant gateway agreement deducts $2\%$ gross fee $+$ $\text{₹}3$ fixed GST on certain payment methods. Bank credits net amount:
  $$\text{Bank Credit} = \text{Gateway Amount} - (\text{Gateway Amount} \times 0.02 + 3.0)$$
- **Target Component**: **Layer 3 Hypothesis Engine** (`PERCENTAGE_FEE` hypothesis template).
- **Target Verification**: Engine evaluates formula parameters `{"fee_percent": 0.02, "flat_fee": 3.0}` and proves hypothesis across Cluster `CLUST_FEE`.

### Scenario C: Many-to-One Settlement Batching
- **Pattern**: 8 individual Gateway payment transactions (totaling $\text{₹}14,000.00$) are aggregated by Razorpay into a single daily payout settlement UTR. Net bank credit equals total minus $2\%$ batch fee ($\text{₹}13,720.00$).
- **Target Component**: **Layer 3 Hypothesis Engine** (`MANY_TO_ONE` settlement aggregator).

---

## 5. Ground Truth & Evaluation Harness Workflow

```
┌────────────────────────────────────────────────────────┐
│             Synthetic Data Generator                   │
└───────────────────────────┬────────────────────────────┘
                            │
            ┌───────────────┴───────────────┐
            ▼                               ▼
┌──────────────────────┐        ┌──────────────────────┐
│     raw_records      │        │    eval_manifest     │
│  (Database Table)    │        │  (Ground Truth Map)  │
└───────────┬───────────┘        └───────────┬──────────┘
            │                               │
            ▼                               │
┌──────────────────────┐                    │
│ Reconciliation Pipeline│                  │
│ (Layer 1 -> 2 -> 3)  │                    │
└───────────┬───────────┘                    │
            │                               │
            ▼                               ▼
┌──────────────────────┐        ┌──────────────────────┐
│  matches & exceptions│ ◄─────►│  Evaluation Harness  │
│    (Actual Output)   │        │   (Precision/Recall) │
└──────────────────────┘        └──────────────────────┘
```

1. **Pipeline Execution**: The reconciliation engine reads `raw_records` without inspecting `gt_match_id` or `gt_exception_type`.
2. **Output Recording**: Resolved matches are written to `matches` and unresolvable items to `exceptions`.
3. **Verification Scorecard**: The evaluation module compares actual `matches.record_ids` against `eval_manifest.ground_truth_matches` to produce:
   - **True Match Rate (Recall)**
   - **Precision (Zero false matches)**
   - **Unresolved Exception Match Accuracy**

---

## 6. How to Run & Reproduce

### Re-Generate Synthetic Dataset
To regenerate a fresh 200-record batch (`data_batch_200.json`):
```bash
PYTHONPATH=. uv run python src/data_generator.py
```

### Ingest Batch into SQLite Database
To reset and populate `reconciliation.db` with the batch:
```bash
PYTHONPATH=. uv run python src/ingest.py
```
