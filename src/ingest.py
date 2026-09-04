import json

from src.data_generator import SyntheticDataGenerator
from src.db import AuditLogger, init_db


def load_and_ingest_batch(
    batch_file: str = "data_batch_200.json", db_file: str = "reconciliation.db"
):
    """Loads synthetic data batch and ingests it into SQLite database with audit logging."""
    conn = init_db(db_file)
    logger = AuditLogger(conn)

    # 1. Load batch json (or generate if missing)
    try:
        with open(batch_file, "r") as f:
            payload = json.load(f)
            records = payload["records"]
            _eval_manifest = payload["eval_manifest"]
    except FileNotFoundError:
        print(f"File {batch_file} not found. Generating new 200-record batch...")
        generator = SyntheticDataGenerator()
        records, _eval_manifest = generator.generate_batch(
            "batch_200", total_records=200
        )

    batch_id = records[0]["batch_id"] if records else "batch_200"

    # 2. Ingest records atomically
    count = logger.ingest_records(batch_id, records)

    print(f"Successfully ingested {count} records into '{db_file}' under batch '{batch_id}'.")

    # 3. Print verification info
    summary = logger.get_batch_summary(batch_id)
    print("\nInitial Ingestion Batch Summary:")
    for k, v in summary.items():
        print(f"  - {k}: {v}")

    conn.close()


if __name__ == "__main__":
    load_and_ingest_batch()
