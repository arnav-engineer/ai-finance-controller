# Database Schema & Audit Trail Specification

This document defines the database architecture and relational schema for the **AI Finance Controller** reconciliation engine.

The system is built on **SQLite** with an **Append-Only Audit Log** as the primary single source of truth. All state transitions, reconciliation decisions, cluster formations, hypothesis evaluations, and exception flags are recorded immutably in `audit_log`. Materialized tables (`matches`, `exceptions`, `clusters`, `hypotheses`) are updated atomically alongside `audit_log` events within single database transactions.

---

## 1. Entity Relationship Diagram

```
                       ┌──────────────────────┐
                       │     raw_records      │
                       └──────────┬───────────┘
                                  │ 1:N
                       ┌──────────┴───────────┐
                       │      audit_log       │ ◄── [Master Append-Only Log]
                       └──────────┬───────────┘
         ┌────────────────────────┼────────────────────────┐
         │ 1:1                    │ 1:1                    │ 1:1
┌────────┴───────┐        ┌───────┴────────┐        ┌──────┴─────────┐
│    matches     │        │   exceptions   │        │   hypotheses    │
└────────────────┘        └───────┬────────┘        └────────────────┘
                                  │ N:1
                          ┌───────┴────────┐
                          │    clusters    │
                          └────────────────┘
```

---

## 2. Complete SQL DDL Script

```sql
PRAGMA foreign_keys = ON;

-- 1. Unified Multi-Source Ingestion Table
CREATE TABLE IF NOT EXISTS raw_records (
    record_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type IN ('GATEWAY', 'BANK', 'LEDGER')),
    external_id TEXT NOT NULL,
    reference_id TEXT,
    amount REAL NOT NULL,
    currency TEXT DEFAULT 'INR',
    fee REAL DEFAULT 0.0,
    tax REAL DEFAULT 0.0,
    timestamp TEXT NOT NULL,
    status TEXT DEFAULT 'UNMATCHED' CHECK (status IN ('UNMATCHED', 'MATCHED', 'EXCEPTION')),
    raw_data JSON NOT NULL,
    -- Ground Truth evaluation tags (isolated from reconciliation engine)
    gt_match_id TEXT,
    gt_exception_type TEXT
);

-- 2. Master Append-Only Audit Log
CREATE TABLE IF NOT EXISTS audit_log (
    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT DEFAULT (datetime('now')),
    batch_id TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK (
        event_type IN (
            'RECORD_INGESTED',
            'LAYER1_EXACT_MATCH',
            'LAYER1_TOLERANCE_MATCH',
            'CLUSTER_CREATED',
            'LAYER2_CLASSIFIED',
            'HYPOTHESIS_TESTED',
            'HYPOTHESIS_PROVEN',
            'HYPOTHESIS_REJECTED',
            'EXCEPTION_FLAGGED',
            'HUMAN_APPROVED'
        )
    ),
    actor TEXT NOT NULL CHECK (
        actor IN (
            'SYSTEM_INGESTION',
            'LAYER1_ENGINE',
            'CLUSTERING_ENGINE',
            'LAYER2_LLM',
            'LAYER3_HYPOTHESIS',
            'EVALUATOR',
            'HUMAN_OPERATOR'
        )
    ),
    record_ids JSON NOT NULL,
    confidence REAL NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    rule_name TEXT NOT NULL,
    details JSON NOT NULL
);

-- 3. Matches State Table
CREATE TABLE IF NOT EXISTS matches (
    match_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    layer TEXT NOT NULL CHECK (layer IN ('LAYER1', 'LAYER2', 'LAYER3')),
    rule_name TEXT NOT NULL,
    confidence REAL NOT NULL,
    record_ids JSON NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    audit_id INTEGER NOT NULL REFERENCES audit_log(audit_id) ON DELETE CASCADE
);

-- 4. Clusters State Table
CREATE TABLE IF NOT EXISTS clusters (
    cluster_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    clustering_method TEXT NOT NULL CHECK (clustering_method IN ('CATEGORICAL', 'DBSCAN')),
    record_count INTEGER NOT NULL,
    features JSON NOT NULL,
    status TEXT DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'RESOLVED'))
);

-- 5. Hypotheses Evaluation Table
CREATE TABLE IF NOT EXISTS hypotheses (
    hypothesis_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    hypothesis_type TEXT NOT NULL CHECK (
        hypothesis_type IN (
            'TIME_OFFSET',
            'FLAT_FEE',
            'PERCENTAGE_FEE',
            'ROUNDING_DIFF',
            'MANY_TO_ONE'
        )
    ),
    parameters JSON NOT NULL,
    cluster_id TEXT REFERENCES clusters(cluster_id) ON DELETE SET NULL,
    match_rate REAL NOT NULL,
    proven BOOLEAN DEFAULT 0 CHECK (proven IN (0, 1)),
    source TEXT NOT NULL CHECK (source IN ('FIXED_LIBRARY', 'LLM_PROPOSED')),
    audit_id INTEGER REFERENCES audit_log(audit_id) ON DELETE CASCADE
);

-- 6. Exceptions State Table
CREATE TABLE IF NOT EXISTS exceptions (
    exception_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    record_id TEXT NOT NULL REFERENCES raw_records(record_id) ON DELETE CASCADE,
    cluster_id TEXT REFERENCES clusters(cluster_id) ON DELETE SET NULL,
    category TEXT NOT NULL CHECK (
        category IN (
            'TIME_OFFSET',
            'FEE_MISMATCH',
            'AMOUNT_OUT_OF_TOLERANCE',
            'MISSING_REF',
            'DUPLICATE_ENTRY',
            'TRUE_SINGLETON'
        )
    ),
    status TEXT DEFAULT 'UNRESOLVED' CHECK (status IN ('UNRESOLVED', 'RESOLVED')),
    audit_id INTEGER NOT NULL REFERENCES audit_log(audit_id) ON DELETE CASCADE
);

-- Optimization Indexes
CREATE INDEX IF NOT EXISTS idx_raw_records_batch_status ON raw_records(batch_id, status);
CREATE INDEX IF NOT EXISTS idx_raw_records_reference ON raw_records(reference_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_batch_event ON audit_log(batch_id, event_type);
CREATE INDEX IF NOT EXISTS idx_matches_batch ON matches(batch_id);
CREATE INDEX IF NOT EXISTS idx_exceptions_batch_status ON exceptions(batch_id, status);
CREATE INDEX IF NOT EXISTS idx_exceptions_record ON exceptions(record_id);
CREATE INDEX IF NOT EXISTS idx_hypotheses_cluster ON hypotheses(cluster_id);
```

---

## 3. Table Specifications & Fields

### 3.1 `raw_records`
Holds multi-source financial records in standardized form.

| Column | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `record_id` | TEXT | PRIMARY KEY | Unique ID (e.g. `GATEWAY_101`, `BANK_202`) |
| `batch_id` | TEXT | NOT NULL | Batch processing identifier |
| `source_type` | TEXT | GATEWAY / BANK / LEDGER | Source system identifier |
| `external_id` | TEXT | NOT NULL | Transaction reference (`pay_xxx`, UTR number, etc.) |
| `reference_id` | TEXT | NULLABLE | Cross-reference identifier (Order ID, Invoice #) |
| `amount` | REAL | NOT NULL | Transaction amount in floating/decimal representation |
| `currency` | TEXT | DEFAULT 'INR' | Currency code |
| `fee` | REAL | DEFAULT 0.0 | Associated fee amount |
| `tax` | REAL | DEFAULT 0.0 | Associated tax amount (e.g. GST) |
| `timestamp` | TEXT | NOT NULL | ISO8601 UTC timestamp |
| `status` | TEXT | UNMATCHED / MATCHED / EXCEPTION | Current record state |
| `raw_data` | JSON | NOT NULL | Complete raw payload from source system |
| `gt_match_id` | TEXT | EVAL ONLY | Hidden ground-truth match cluster key |
| `gt_exception_type` | TEXT | EVAL ONLY | Hidden ground-truth exception label |

### 3.2 `audit_log`
Immutable master ledger of all actions and evidence.

| Column | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `audit_id` | INTEGER | PK AUTOINCREMENT | Sequential event ID |
| `timestamp` | TEXT | DEFAULT datetime('now') | Event creation timestamp |
| `batch_id` | TEXT | NOT NULL | Batch ID |
| `event_type` | TEXT | ENUM | Type of pipeline action executed |
| `actor` | TEXT | ENUM | Module or component executing action |
| `record_ids` | JSON | NOT NULL | Array of affected record IDs |
| `confidence` | REAL | 0.0 - 1.0 | Match or classification confidence |
| `rule_name` | TEXT | NOT NULL | Identifier of the rule or hypothesis |
| `details` | JSON | NOT NULL | Structured evidence payload (deltas, math, reasoning) |

### 3.3 `matches`
Materialized state of resolved records.

| Column | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `match_id` | TEXT | PRIMARY KEY | Unique match entry ID |
| `batch_id` | TEXT | NOT NULL | Batch ID |
| `layer` | TEXT | LAYER1 / LAYER2 / LAYER3 | Engine layer that performed the match |
| `rule_name` | TEXT | NOT NULL | Rule or hypothesis name |
| `confidence` | REAL | 0.0 - 1.0 | Match confidence |
| `record_ids` | JSON | NOT NULL | Matched record IDs array |
| `created_at` | TEXT | DEFAULT datetime('now') | Match timestamp |
| `audit_id` | INTEGER | FK -> audit_log | Link to audit record |

### 3.4 `clusters`
Groups of unmatched records aggregated by categorical or numeric features.

| Column | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `cluster_id` | TEXT | PRIMARY KEY | Unique cluster identifier |
| `batch_id` | TEXT | NOT NULL | Batch ID |
| `clustering_method` | TEXT | CATEGORICAL / DBSCAN | Clustering strategy used |
| `record_count` | INTEGER | NOT NULL | Number of records in cluster |
| `features` | JSON | NOT NULL | Feature summary (avg time delta, source pair, etc.) |
| `status` | TEXT | OPEN / RESOLVED | Resolution state of cluster |

### 3.5 `hypotheses`
Systemic patterns tested against clusters in Layer 3.

| Column | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `hypothesis_id` | TEXT | PRIMARY KEY | Unique hypothesis ID |
| `batch_id` | TEXT | NOT NULL | Batch ID |
| `hypothesis_type` | TEXT | ENUM | Category of systemic pattern |
| `parameters` | JSON | NOT NULL | Parameter values (offset_seconds, fee_percent, etc.) |
| `cluster_id` | TEXT | FK -> clusters | Target cluster |
| `match_rate` | REAL | NOT NULL | Fraction of cluster records resolved ($\ge 0.8$ to prove) |
| `proven` | BOOLEAN | 0 or 1 | Whether hypothesis passed verification threshold |
| `source` | TEXT | FIXED_LIBRARY / LLM_PROPOSED | Provenance of hypothesis |
| `audit_id` | INTEGER | FK -> audit_log | Link to audit record |

### 3.6 `exceptions`
Unresolved or flagged records requiring classification or human review.

| Column | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `exception_id` | TEXT | PRIMARY KEY | Unique exception identifier |
| `batch_id` | TEXT | NOT NULL | Batch ID |
| `record_id` | TEXT | FK -> raw_records | Target record |
| `cluster_id` | TEXT | FK -> clusters | Assigned cluster (if any) |
| `category` | TEXT | ENUM | Exception category |
| `status` | TEXT | UNRESOLVED / RESOLVED | Current exception resolution status |
| `audit_id` | INTEGER | FK -> audit_log | Link to audit log entry |

---

## 4. JSON Field Schemas

### 4.1 `audit_log.details` (Layer 1 Match Payload)
```json
{
  "match_type": "1_TO_1_EXACT",
  "key_used": "reference_id",
  "key_value": "order_99812",
  "amount_gateway": 1500.0,
  "amount_bank": 1500.0,
  "amount_delta": 0.0,
  "time_delta_seconds": 12
}
```

### 4.2 `audit_log.details` (Layer 3 Hypothesis Proven Payload)
```json
{
  "hypothesis_type": "TIME_OFFSET",
  "cluster_id": "CLUST_02",
  "parameters": {
    "offset_seconds": 19800,
    "description": "UTC to IST 5h 30m delta"
  },
  "total_records_in_cluster": 12,
  "resolved_records_count": 12,
  "match_rate": 1.0,
  "threshold_required": 0.8
}
```

### 4.3 `clusters.features`
```json
{
  "source_pair": ["GATEWAY", "BANK"],
  "payment_method": "UPI",
  "avg_amount_delta": 3.0,
  "avg_time_delta_seconds": 19805.2,
  "time_delta_std_dev": 2.1
}
```

---

## 5. Audit Logging Workflow & Transaction Safety

To guarantee atomic state synchronization:
1. Every pipeline step executes inside a single SQLite database transaction (`BEGIN TRANSACTION`).
2. The event is written to `audit_log` first, yielding an `audit_id`.
3. State update tables (`matches`, `exceptions`, `clusters`, `hypotheses`, `raw_records`) are updated referencing `audit_id`.
4. Transaction is committed (`COMMIT`).

---

## 6. Proactive Interrogation Query Patterns

### Query 1: Single Record Evidence Trail
```sql
SELECT 
    audit_id, 
    timestamp, 
    event_type, 
    actor, 
    rule_name, 
    confidence, 
    details
FROM audit_log
WHERE json_extract(record_ids, '$') LIKE '%GATEWAY_101%'
ORDER BY audit_id ASC;
```

### Query 2: Proven Hypotheses & Impacted Record Count
```sql
SELECT 
    h.hypothesis_id,
    h.hypothesis_type,
    h.parameters,
    h.match_rate,
    h.source,
    c.record_count
FROM hypotheses h
JOIN clusters c ON h.cluster_id = c.cluster_id
WHERE h.proven = 1 AND h.batch_id = 'batch_01';
```
