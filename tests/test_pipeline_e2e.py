import sqlite3

from main import run_pipeline
from src.db import AuditLogger


def test_end_to_end_pipeline_50_batch(tmp_path):
    """End-to-end integration test for 50-record reconciliation pipeline."""
    db_file = str(tmp_path / "recon_e2e.db")
    run_pipeline("batch_e2e_50", total_records=50, db_file=db_file)

    conn = sqlite3.connect(db_file)
    logger = AuditLogger(conn)
    summary = logger.get_batch_summary("batch_e2e_50")

    assert summary["total_records"] == 50
    assert summary["matched_records"] >= 40
    assert summary["match_rate"] >= 0.85
    assert summary["exception_records"] <= 10

    conn.close()
