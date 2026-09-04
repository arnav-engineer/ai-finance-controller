import sqlite3
import pytest
from src.db import init_db, AuditLogger
from src.data_generator import SyntheticDataGenerator
from src.exact_matcher import ExactMatcher


@pytest.fixture
def populated_db(tmp_path):
    """Fixture initializing DB and ingesting a 50-record batch."""
    db_path = str(tmp_path / "recon_matcher_test.db")
    conn = init_db(db_path)
    logger = AuditLogger(conn)

    generator = SyntheticDataGenerator(seed=42)
    records, eval_manifest = generator.generate_batch("batch_test_matcher", total_records=50)
    logger.ingest_records("batch_test_matcher", records)

    yield conn, eval_manifest
    conn.close()


def test_exact_matcher_execution_and_precision(populated_db):
    """Verifies that ExactMatcher matches happy-path pairs/triplets with 100% precision."""
    conn, eval_manifest = populated_db
    matcher = ExactMatcher(conn)

    results = matcher.run("batch_test_matcher")

    assert results["total_records_matched"] > 0
    assert results["remaining_unmatched"] < results["initial_unmatched"]

    # Verify zero false positive matches against ground truth
    cursor = conn.cursor()
    cursor.execute("SELECT record_ids FROM matches WHERE batch_id = 'batch_test_matcher'")
    matches = cursor.fetchall()

    for (r_ids_json,) in matches:
        rec_ids = eval(r_ids_json) if isinstance(r_ids_json, str) else r_ids_json
        placeholders = ",".join("?" for _ in rec_ids)
        cursor.execute(f"SELECT gt_match_id FROM raw_records WHERE record_id IN ({placeholders})", rec_ids)
        gt_ids = set(row[0] for row in cursor.fetchall())

        assert len(gt_ids) == 1, f"False positive match detected in record group: {rec_ids}"
        assert None not in gt_ids
