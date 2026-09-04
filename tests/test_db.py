import pytest

from src.db import AuditLogger, init_db


@pytest.fixture
def temp_db(tmp_path):
    """Fixture providing a temporary SQLite database for testing."""
    db_path = str(tmp_path / "test_recon.db")
    conn = init_db(db_path)
    yield conn
    conn.close()


def test_init_db(temp_db):
    """Verifies that init_db creates all required tables and enables WAL mode."""
    cursor = temp_db.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = {row[0] for row in cursor.fetchall()}

    expected_tables = {"raw_records", "audit_log", "matches", "clusters", "hypotheses", "exceptions"}
    assert expected_tables.issubset(tables)


def test_audit_logger_ingest_records(temp_db):
    """Verifies atomic record ingestion and audit log event creation."""
    logger = AuditLogger(temp_db)
    sample_records = [
        {
            "record_id": "REC_TEST_01",
            "source_type": "GATEWAY",
            "external_id": "pay_test01",
            "reference_id": "order_test01",
            "amount": 1000.0,
            "timestamp": "2026-09-01T10:00:00+00:00",
            "status": "UNMATCHED",
            "raw_data": {"test": True},
        },
        {
            "record_id": "REC_TEST_02",
            "source_type": "BANK",
            "external_id": "UTR_TEST01",
            "reference_id": "order_test01",
            "amount": 1000.0,
            "timestamp": "2026-09-01T10:01:00+00:00",
            "status": "UNMATCHED",
            "raw_data": {"test": True},
        },
    ]

    count = logger.ingest_records("batch_test", sample_records)
    assert count == 2

    # Verify audit log event
    cursor = temp_db.cursor()
    cursor.execute("SELECT event_type, actor FROM audit_log WHERE batch_id = 'batch_test'")
    events = cursor.fetchall()
    assert len(events) == 1
    assert events[0][0] == "RECORD_INGESTED"
    assert events[0][1] == "SYSTEM_INGESTION"


def test_audit_logger_log_match_and_summary(temp_db):
    """Verifies logging matches updates record status and batch summary metrics."""
    logger = AuditLogger(temp_db)
    sample_records = [
        {
            "record_id": "REC_M01",
            "source_type": "GATEWAY",
            "external_id": "p1",
            "reference_id": "o1",
            "amount": 500.0,
            "timestamp": "2026-09-01T10:00:00+00:00",
        },
        {
            "record_id": "REC_M02",
            "source_type": "BANK",
            "external_id": "u1",
            "reference_id": "o1",
            "amount": 500.0,
            "timestamp": "2026-09-01T10:00:00+00:00",
        },
    ]
    logger.ingest_records("batch_summary_test", sample_records)

    match_id = logger.log_match(
        batch_id="batch_summary_test",
        layer="EXACT_MATCHER",
        rule_name="exact_1to1_key_amount_match",
        confidence=1.0,
        record_ids=["REC_M01", "REC_M02"],
        details={"test": True},
    )
    assert match_id.startswith("MATCH_")

    summary = logger.get_batch_summary("batch_summary_test")
    assert summary["total_records"] == 2
    assert summary["matched_records"] == 2
    assert summary["unmatched_records"] == 0
    assert summary["match_rate"] == 1.0


def test_clear_batch(temp_db):
    """Verifies clear_batch removes all data for a specific batch_id idempotently."""
    logger = AuditLogger(temp_db)
    sample = [
        {
            "record_id": "REC_C01",
            "source_type": "GATEWAY",
            "external_id": "p",
            "amount": 100.0,
            "timestamp": "2026-09-01T10:00:00+00:00",
        }
    ]
    logger.ingest_records("batch_clear", sample)
    logger.clear_batch("batch_clear")

    cursor = temp_db.cursor()
    cursor.execute("SELECT COUNT(*) FROM raw_records WHERE batch_id = 'batch_clear'")
    assert cursor.fetchone()[0] == 0
