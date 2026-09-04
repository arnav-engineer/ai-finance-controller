import pytest

from src.clustering import ClusteringEngine
from src.data_generator import SyntheticDataGenerator
from src.db import AuditLogger, init_db
from src.exact_matcher import ExactMatcher
from src.hypothesis_engine import HypothesisEngine


@pytest.fixture
def post_clustering_db(tmp_path):
    """Fixture providing DB after Pass 1 and Pass 2 execution."""
    db_path = str(tmp_path / "recon_hyp_test.db")
    conn = init_db(db_path)
    logger = AuditLogger(conn)

    generator = SyntheticDataGenerator(seed=42)
    records, _eval_manifest = generator.generate_batch("batch_test_hyp", total_records=50)
    logger.ingest_records("batch_test_hyp", records)

    matcher = ExactMatcher(conn)
    matcher.run("batch_test_hyp")

    clusterer = ClusteringEngine(conn)
    clusterer.run("batch_test_hyp")

    yield conn
    conn.close()


def test_hypothesis_engine_proven_templates(post_clustering_db):
    """Verifies that HypothesisEngine tests and proves systemic hypotheses."""
    engine = HypothesisEngine(post_clustering_db, verbose=False)
    results = engine.run("batch_test_hyp")

    assert results["hypotheses_tested"] >= 1
    assert results["hypotheses_proven"] >= 1
    assert results["records_matched_by_hypotheses"] > 0
    assert results["singletons_classified"] > 0

    summary = results["final_batch_summary"]
    assert summary["matched_records"] >= 40
    assert summary["match_rate"] >= 0.80
