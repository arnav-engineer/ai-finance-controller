import sqlite3
import json
import uuid
from typing import List, Dict, Any, Optional

SCHEMA_DDL = """
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
            'EXACT_MATCHER',
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
    layer TEXT NOT NULL CHECK (layer IN ('EXACT_MATCHER', 'LAYER1', 'LAYER2', 'LAYER3')),
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
"""


def init_db(db_path: str = "reconciliation.db") -> sqlite3.Connection:
    """Initializes the SQLite database schema and returns a connection with WAL mode enabled."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.executescript(SCHEMA_DDL)
    conn.commit()
    return conn


class AuditLogger:
    """
    Atomic transaction wrapper for recording events to audit_log
    and updating state tables (raw_records, matches, exceptions, hypotheses).
    """

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def ingest_records(self, batch_id: str, records: List[Dict[str, Any]]) -> int:
        """Ingests raw records into raw_records and logs RECORD_INGESTED in audit_log."""
        cursor = self.conn.cursor()
        ingested_count = 0

        with self.conn:
            for rec in records:
                cursor.execute(
                    """
                    INSERT INTO raw_records (
                        record_id, batch_id, source_type, external_id, reference_id,
                        amount, currency, fee, tax, timestamp, status, raw_data,
                        gt_match_id, gt_exception_type
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        rec["record_id"],
                        batch_id,
                        rec["source_type"],
                        rec["external_id"],
                        rec.get("reference_id"),
                        rec["amount"],
                        rec.get("currency", "INR"),
                        rec.get("fee", 0.0),
                        rec.get("tax", 0.0),
                        rec["timestamp"],
                        rec.get("status", "UNMATCHED"),
                        json.dumps(rec.get("raw_data", {})),
                        rec.get("gt_match_id"),
                        rec.get("gt_exception_type"),
                    ),
                )
                ingested_count += 1

            all_record_ids = [r["record_id"] for r in records]
            cursor.execute(
                """
                INSERT INTO audit_log (batch_id, event_type, actor, record_ids, confidence, rule_name, details)
                VALUES (?, 'RECORD_INGESTED', 'SYSTEM_INGESTION', ?, 1.0, 'ingest_batch', ?)
                """,
                (
                    batch_id,
                    json.dumps(all_record_ids),
                    json.dumps({"count": ingested_count, "batch_id": batch_id}),
                ),
            )
        return ingested_count

    def log_match(
        self,
        batch_id: str,
        layer: str,
        rule_name: str,
        confidence: float,
        record_ids: List[str],
        details: Dict[str, Any],
        actor: str = "LAYER1_ENGINE",
        event_type: str = "LAYER1_EXACT_MATCH",
    ) -> str:
        """Atomically logs a match event to audit_log, updates raw_records status, and creates a match row."""
        match_id = f"MATCH_{uuid.uuid4().hex[:8]}"
        cursor = self.conn.cursor()

        with self.conn:
            # 1. Insert into audit_log
            cursor.execute(
                """
                INSERT INTO audit_log (batch_id, event_type, actor, record_ids, confidence, rule_name, details)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    batch_id,
                    event_type,
                    actor,
                    json.dumps(record_ids),
                    confidence,
                    rule_name,
                    json.dumps(details),
                ),
            )
            audit_id = cursor.lastrowid

            # 2. Insert into matches table
            cursor.execute(
                """
                INSERT INTO matches (match_id, batch_id, layer, rule_name, confidence, record_ids, audit_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    match_id,
                    batch_id,
                    layer,
                    rule_name,
                    confidence,
                    json.dumps(record_ids),
                    audit_id,
                ),
            )

            # 3. Update raw_records status to MATCHED
            placeholders = ",".join("?" for _ in record_ids)
            cursor.execute(
                f"UPDATE raw_records SET status = 'MATCHED' WHERE record_id IN ({placeholders})",
                record_ids,
            )

        return match_id

    def log_cluster(
        self,
        batch_id: str,
        cluster_id: str,
        clustering_method: str,
        record_ids: List[str],
        features: Dict[str, Any],
    ) -> None:
        """Atomically logs cluster creation to audit_log and clusters table."""
        cursor = self.conn.cursor()

        with self.conn:
            cursor.execute(
                """
                INSERT INTO audit_log (batch_id, event_type, actor, record_ids, confidence, rule_name, details)
                VALUES (?, 'CLUSTER_CREATED', 'CLUSTERING_ENGINE', ?, 1.0, ?, ?)
                """,
                (
                    batch_id,
                    json.dumps(record_ids),
                    f"cluster_{clustering_method.lower()}",
                    json.dumps({"cluster_id": cluster_id, "features": features}),
                ),
            )

            cursor.execute(
                """
                INSERT OR REPLACE INTO clusters (cluster_id, batch_id, clustering_method, record_count, features, status)
                VALUES (?, ?, ?, ?, ?, 'OPEN')
                """,
                (
                    cluster_id,
                    batch_id,
                    clustering_method,
                    len(record_ids),
                    json.dumps(features),
                ),
            )

    def log_hypothesis(
        self,
        batch_id: str,
        hypothesis_id: str,
        hypothesis_type: str,
        parameters: Dict[str, Any],
        cluster_id: Optional[str],
        match_rate: float,
        proven: bool,
        source: str,
        details: Dict[str, Any],
        actor: str = "LAYER3_HYPOTHESIS",
    ) -> None:
        """Logs a hypothesis test and result into audit_log and hypotheses table."""
        cursor = self.conn.cursor()
        event_type = "HYPOTHESIS_PROVEN" if proven else "HYPOTHESIS_REJECTED"

        with self.conn:
            cursor.execute(
                """
                INSERT INTO audit_log (batch_id, event_type, actor, record_ids, confidence, rule_name, details)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    batch_id,
                    event_type,
                    actor,
                    json.dumps(details.get("record_ids", [])),
                    match_rate,
                    f"hypothesis_{hypothesis_type.lower()}",
                    json.dumps(details),
                ),
            )
            audit_id = cursor.lastrowid

            cursor.execute(
                """
                INSERT INTO hypotheses (hypothesis_id, batch_id, hypothesis_type, parameters, cluster_id, match_rate, proven, source, audit_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    hypothesis_id,
                    batch_id,
                    hypothesis_type,
                    json.dumps(parameters),
                    cluster_id,
                    match_rate,
                    1 if proven else 0,
                    source,
                    audit_id,
                ),
            )

            if proven and cluster_id:
                cursor.execute(
                    "UPDATE clusters SET status = 'RESOLVED' WHERE cluster_id = ?",
                    (cluster_id,),
                )

    def log_exception(
        self,
        batch_id: str,
        record_id: str,
        category: str,
        details: Dict[str, Any],
        cluster_id: Optional[str] = None,
    ) -> str:
        """Logs an exception for an unresolvable record."""
        exception_id = f"EXC_{uuid.uuid4().hex[:8]}"
        cursor = self.conn.cursor()

        with self.conn:
            cursor.execute(
                """
                INSERT INTO audit_log (batch_id, event_type, actor, record_ids, confidence, rule_name, details)
                VALUES (?, 'EXCEPTION_FLAGGED', 'LAYER2_LLM', ?, 0.0, ?, ?)
                """,
                (
                    batch_id,
                    json.dumps([record_id]),
                    f"exception_{category.lower()}",
                    json.dumps(details),
                ),
            )
            audit_id = cursor.lastrowid

            cursor.execute(
                """
                INSERT INTO exceptions (exception_id, batch_id, record_id, cluster_id, category, status, audit_id)
                VALUES (?, ?, ?, ?, ?, 'UNRESOLVED', ?)
                """,
                (
                    exception_id,
                    batch_id,
                    record_id,
                    cluster_id,
                    category,
                    audit_id,
                ),
            )

            cursor.execute(
                "UPDATE raw_records SET status = 'EXCEPTION' WHERE record_id = ?",
                (record_id,),
            )

        return exception_id

    def get_record_history(self, record_id: str) -> List[Dict[str, Any]]:
        """Queries the full evidence trail for a specific record for interrogation chat."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT audit_id, timestamp, batch_id, event_type, actor, confidence, rule_name, details
            FROM audit_log
            WHERE record_ids LIKE ?
            ORDER BY audit_id ASC
            """,
            (f"%{record_id}%",),
        )
        rows = cursor.fetchall()
        history = []
        for r in rows:
            history.append(
                {
                    "audit_id": r[0],
                    "timestamp": r[1],
                    "batch_id": r[2],
                    "event_type": r[3],
                    "actor": r[4],
                    "confidence": r[5],
                    "rule_name": r[6],
                    "details": json.loads(r[7]),
                }
            )
        return history

    def get_batch_summary(self, batch_id: str) -> Dict[str, Any]:
        """Returns batch reconciliation metrics (matches, exceptions, match rate)."""
        cursor = self.conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM raw_records WHERE batch_id = ?", (batch_id,))
        total_records = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM raw_records WHERE batch_id = ? AND status = 'MATCHED'",
            (batch_id,),
        )
        matched_records = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM raw_records WHERE batch_id = ? AND status = 'EXCEPTION'",
            (batch_id,),
        )
        exception_records = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM raw_records WHERE batch_id = ? AND status = 'UNMATCHED'",
            (batch_id,),
        )
        unmatched_records = cursor.fetchone()[0]

        match_rate = (matched_records / total_records) if total_records > 0 else 0.0

        return {
            "batch_id": batch_id,
            "total_records": total_records,
            "matched_records": matched_records,
            "exception_records": exception_records,
            "unmatched_records": unmatched_records,
            "match_rate": round(match_rate, 4),
        }


if __name__ == "__main__":
    db_file = "reconciliation.db"
    conn = init_db(db_file)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in cursor.fetchall()]
    print(f"Database successfully created at: {db_file}")
    print("Tables initialized:")
    for t in tables:
        if not t.startswith("sqlite_"):
            print(f"  - {t}")
    conn.close()

