import sqlite3
import pytest
from src.db import init_db, AuditLogger
from src.data_generator import SyntheticDataGenerator
from src.exact_matcher import ExactMatcher
from src.clustering import ClusteringEngine
from src.hypothesis_engine import HypothesisEngine
from src.cli import HumanInTheLoopCLI


@pytest.fixture
def cli_db(tmp_path):
    """Fixture initializing a database and populating it with pipeline outputs for CLI testing."""
    db_file = str(tmp_path / "cli_test.db")
    conn = init_db(db_file)
    logger = AuditLogger(conn)

    generator = SyntheticDataGenerator(seed=42)
    records, eval_manifest = generator.generate_batch("batch_cli_test", total_records=50)
    logger.ingest_records("batch_cli_test", records)

    ExactMatcher(conn).run("batch_cli_test")
    ClusteringEngine(conn).run("batch_cli_test")
    HypothesisEngine(conn, verbose=False).run("batch_cli_test")

    conn.close()
    return db_file


def test_cli_normalize_record_id(cli_db):
    """Verifies record ID normalization in HumanInTheLoopCLI."""
    cli = HumanInTheLoopCLI(db_file=cli_db)

    assert cli._normalize_record_id("rec 0001") == "REC_0001"
    assert cli._normalize_record_id("1") == "REC_0001"
    assert cli._normalize_record_id("REC_0045") == "REC_0045"
    assert cli._normalize_record_id("REC45") == "REC_0045"
    cli.conn.close()


def test_cli_show_pending_hypotheses(cli_db):
    """Verifies retrieval of pending systemic hypotheses."""
    cli = HumanInTheLoopCLI(db_file=cli_db)
    hyp_ids = cli.show_pending_hypotheses("batch_cli_test")

    assert isinstance(hyp_ids, list)
    assert len(hyp_ids) >= 1
    cli.conn.close()


def test_cli_interrogate_record(cli_db, capsys):
    """Verifies record audit trail interrogation."""
    cli = HumanInTheLoopCLI(db_file=cli_db)
    cli.interrogate_record("REC_0001")

    captured = capsys.readouterr()
    assert "PROACTIVE INTERROGATION CHAT" in captured.out
    assert "REC_0001" in captured.out
    cli.conn.close()


def test_cli_test_custom_human_rule(cli_db, capsys):
    """Verifies testing custom human rules against clusters."""
    cli = HumanInTheLoopCLI(db_file=cli_db)

    # Get a cluster ID
    cursor = cli.conn.cursor()
    cursor.execute("SELECT cluster_id FROM clusters WHERE batch_id = 'batch_cli_test' LIMIT 1")
    row = cursor.fetchone()
    assert row is not None
    cluster_id = row[0]

    cli.test_custom_human_rule(cluster_id=cluster_id, fee_percent=0.02, flat_fee=3.0)
    captured = capsys.readouterr()
    assert "HUMAN LIVE RULE TEST" in captured.out
    cli.conn.close()
