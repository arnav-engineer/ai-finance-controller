from src.data_generator import SyntheticDataGenerator


def test_synthetic_data_generator_50_batch():
    """Verifies generation of exactly 50 synthetic records with valid schemas."""
    generator = SyntheticDataGenerator(seed=123)
    records, eval_manifest = generator.generate_batch("batch_50_test", total_records=50)

    assert len(records) == 50
    assert eval_manifest["batch_id"] == "batch_50_test"
    assert len(eval_manifest["ground_truth_matches"]) > 0

    # Verify canonical record fields
    for rec in records:
        assert "record_id" in rec
        assert "batch_id" in rec
        assert rec["source_type"] in ("GATEWAY", "BANK", "LEDGER")
        assert "amount" in rec
        assert rec["amount"] > 0
        assert "timestamp" in rec
        assert rec["status"] == "UNMATCHED"


def test_synthetic_data_generator_200_batch():
    """Verifies generation of 200 synthetic records."""
    generator = SyntheticDataGenerator(seed=456)
    records, _eval_manifest = generator.generate_batch("batch_200_test", total_records=200)

    assert len(records) == 200
    sources = {r["source_type"] for r in records}
    assert sources == {"GATEWAY", "BANK", "LEDGER"}
