from src.carbon_tracker import AuditCarbonTracker


def test_audit_carbon_tracker():
    """Verifies AuditCarbonTracker initialization, start, stop, and metrics aggregation."""
    tracker = AuditCarbonTracker(country_iso_code="IND", project_name="test_ai_finance_controller")
    tracker.start()

    metrics = tracker.stop(total_records=50)

    assert "emissions_kg_co2eq" in metrics
    assert "emissions_mg_co2eq" in metrics
    assert "emissions_per_tx_mg" in metrics
    assert metrics["total_records"] == 50
    assert metrics["project_name"] == "test_ai_finance_controller"
    assert metrics["country_iso_code"] == "IND"
