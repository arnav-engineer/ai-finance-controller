import sqlite3
import pytest
from src.db import init_db, AuditLogger
from src.data_generator import SyntheticDataGenerator
from src.exact_matcher import ExactMatcher
from src.clustering import ClusteringEngine
from src.hypothesis_engine import HypothesisEngine
from src.evaluator import Evaluator


@pytest.fixture
def post_pipeline_db(tmp_path):
    """Fixture providing DB after full reconciliation pipeline run."""
    db_path = str(tmp_path / "recon_eval_test.db")
    conn = init_db(db_path)
    logger = AuditLogger(conn)

    generator = SyntheticDataGenerator(seed=42)
    records, eval_manifest = generator.generate_batch("batch_test_eval", total_records=50)
    logger.ingest_records("batch_test_eval", records)

    ExactMatcher(conn).run("batch_test_eval")
    ClusteringEngine(conn).run("batch_test_eval")
    HypothesisEngine(conn, verbose=False).run("batch_test_eval")

    yield conn
    conn.close()


def test_evaluator_scorecard(post_pipeline_db):
    """Verifies that Evaluator calculates 100% precision and valid scorecard metrics."""
    evaluator = Evaluator(post_pipeline_db)
    report = evaluator.evaluate_batch("batch_test_eval")

    assert report["total_records"] == 50
    assert report["matched_records"] >= 40
    assert report["overall_match_rate"] >= 0.80
    assert report["match_precision"] == 1.0  # Zero false positives constraint
    assert report["match_recall"] >= 0.80
    assert len(report["unmatched_details"]) == report["exception_records"]
