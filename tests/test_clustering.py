import sqlite3
import pytest
from src.db import init_db, AuditLogger
from src.data_generator import SyntheticDataGenerator
from src.exact_matcher import ExactMatcher
from src.clustering import ClusteringEngine


@pytest.fixture
def post_matcher_db(tmp_path):
    """Fixture providing DB after Pass 1 ExactMatcher run."""
    db_path = str(tmp_path / "recon_cluster_test.db")
    conn = init_db(db_path)
    logger = AuditLogger(conn)

    generator = SyntheticDataGenerator(seed=42)
    records, eval_manifest = generator.generate_batch("batch_test_cluster", total_records=50)
    logger.ingest_records("batch_test_cluster", records)

    matcher = ExactMatcher(conn)
    matcher.run("batch_test_cluster")

    yield conn
    conn.close()


def test_clustering_engine(post_matcher_db):
    """Verifies that ClusteringEngine groups unmatched records into systemic clusters."""
    clusterer = ClusteringEngine(post_matcher_db)
    results = clusterer.run("batch_test_cluster")

    assert results["total_clusters_created"] >= 1
    assert results["records_in_clusters"] > 0
    assert results["unclustered_singletons"] > 0

    cursor = post_matcher_db.cursor()
    cursor.execute("SELECT COUNT(*) FROM clusters WHERE batch_id = 'batch_test_cluster'")
    cluster_count_in_db = cursor.fetchone()[0]
    assert cluster_count_in_db == results["total_clusters_created"]
