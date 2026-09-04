import json
import sqlite3
from src.db import init_db, AuditLogger
from src.data_generator import SyntheticDataGenerator
from src.exact_matcher import ExactMatcher
from src.clustering import ClusteringEngine
from src.hypothesis_engine import HypothesisEngine
from src.evaluator import Evaluator


def run_pipeline(batch_id: str = "batch_50", total_records: int = 50, db_file: str = "reconciliation.db"):
    """
    Runs the end-to-end AI Finance Controller reconciliation pipeline across a 50-record batch.
    
    Stages:
      1. Synthetic Multi-Source Ingestion & Ground-Truth Setup
      2. Pass 1: ExactMatcher (Deterministic 1:1 Pairs & 1:1:1 Triplets)
      3. Pass 2: ClusteringEngine (Categorical & DBSCAN Sub-Clustering)
      4. Pass 3: HypothesisEngine (Groq API Powered Pattern Discovery & Exception Classification)
      5. Evaluation Scorecard Report
    """
    print("\n" + "=" * 70)
    print(f"   STARTING RECONCILIATION PIPELINE (Batch: {batch_id}, Size: {total_records} Records)")
    print("=" * 70)

    # --- STAGE 1: Database Setup & Batch Generation / Ingestion ---
    print("\n[STAGE 1/5] Ingesting Multi-Source Records...")
    conn = init_db(db_file)
    logger = AuditLogger(conn)

    generator = SyntheticDataGenerator()
    records, eval_manifest = generator.generate_batch(batch_id=batch_id, total_records=total_records)
    
    ingested_count = logger.ingest_records(batch_id, records)
    print(f"  ✓ Ingested {ingested_count} records into '{db_file}' across GATEWAY, BANK, and LEDGER sources.")

    # --- STAGE 2: ExactMatcher (Pass 1) ---
    print("\n[STAGE 2/5] Running Pass 1: ExactMatcher (Deterministic Engine)...")
    matcher = ExactMatcher(conn)
    pass1_results = matcher.run(batch_id)
    print(f"  ✓ Pass 1 Exact Matches      : {pass1_results['pass1_exact_1to1_matches']} pairs")
    print(f"  ✓ Pass 1 Exact Triplets     : {pass1_results['pass2_exact_triplet_matches']} triplets")
    print(f"  ✓ Stage Total Records Matched: {pass1_results['total_records_matched']}/{total_records} ({pass1_results['total_records_matched']/total_records*100:.1f}%)")
    print(f"  ✓ Remaining Unmatched        : {pass1_results['remaining_unmatched']} records")

    # --- STAGE 3: ClusteringEngine (Pass 2) ---
    print("\n[STAGE 3/5] Running Pass 2: ClusteringEngine (Categorical & DBSCAN)...")
    clusterer = ClusteringEngine(conn)
    pass2_results = clusterer.run(batch_id)
    print(f"  ✓ Systemic Clusters Formed  : {pass2_results['total_clusters_created']} clusters ({pass2_results['records_in_clusters']} records)")
    print(f"  ✓ Isolated Singletons        : {pass2_results['unclustered_singletons']} records")

    # --- STAGE 4: HypothesisEngine & Exception Classification (Pass 3) ---
    print("\n[STAGE 4/5] Running Pass 3: HypothesisEngine (Groq API Pattern Discovery)...")
    hypothesis_engine = HypothesisEngine(conn)
    pass3_results = hypothesis_engine.run(batch_id)
    print(f"  ✓ Systemic Hypotheses Proven : {pass3_results['hypotheses_proven']}/{pass3_results['hypotheses_tested']} tested")
    print(f"  ✓ Layer 3 Additional Matches : {pass3_results['records_matched_by_hypotheses']} records")
    print(f"  ✓ Singletons Classified     : {pass3_results['singletons_classified']} records")

    # --- STAGE 5: Evaluation Scorecard & Accuracy Audit ---
    print("\n[STAGE 5/5] Generating Evaluation Scorecard & Ground-Truth Accuracy Audit...")
    evaluator = Evaluator(conn)
    scorecard = evaluator.evaluate_batch(batch_id)
    evaluator.print_scorecard(scorecard)

    conn.close()


if __name__ == "__main__":
    run_pipeline("batch_50", total_records=50)
