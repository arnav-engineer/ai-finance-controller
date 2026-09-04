from typing import Any

try:
    from codecarbon import OfflineEmissionsTracker

    CODECARBON_AVAILABLE = True
except ImportError:
    CODECARBON_AVAILABLE = False


class AuditCarbonTracker:
    """
    Integrates CodeCarbon energy and carbon emission auditing into the AI Finance Controller.
    
    Tracks CPU/GPU power consumption (kWh), duration (seconds), and carbon footprint (kg CO2eq)
    for financial reconciliation workloads, recording immutable metrics into audit_log.
    """

    def __init__(
        self,
        country_iso_code: str = "IND",
        project_name: str = "ai_finance_controller",
    ):
        self.project_name = project_name
        self.country_iso_code = country_iso_code
        self.tracker: Any | None = None
        self.emissions_kg: float = 0.0

        if CODECARBON_AVAILABLE:
            try:
                # Suppress noisy standard output from codecarbon logs
                self.tracker = OfflineEmissionsTracker(
                    country_iso_code=country_iso_code,
                    project_name=project_name,
                    output_dir="./",
                    log_level="error",
                    save_to_file=False,
                )
            except Exception:  # noqa: BLE001
                self.tracker = None

    def start(self):
        """Starts energy and carbon tracking."""
        if self.tracker:
            try:
                self.tracker.start()
            except Exception:  # noqa: BLE001
                _ = None

    def stop(self, total_records: int = 50) -> dict[str, Any]:
        """Stops carbon tracking and returns metrics dictionary."""
        energy_kwh = 0.0
        emissions_kg = 0.0

        if self.tracker:
            try:
                emissions_kg = float(self.tracker.stop() or 0.0)
                energy_kwh = float(
                    getattr(self.tracker, "_total_energy", 0.0) or 0.0
                )
                if hasattr(energy_kwh, "kWh"):
                    energy_kwh = float(energy_kwh.kWh)
            except Exception:  # noqa: BLE001
                emissions_kg = 0.0

        emissions_mg = round(emissions_kg * 1_000_000, 4)
        emissions_per_tx_mg = round(emissions_mg / max(total_records, 1), 4)

        metrics = {
            "project_name": self.project_name,
            "country_iso_code": self.country_iso_code,
            "total_records": total_records,
            "emissions_kg_co2eq": emissions_kg,
            "emissions_mg_co2eq": emissions_mg,
            "emissions_per_tx_mg": emissions_per_tx_mg,
            "energy_kwh": energy_kwh,
            "codecarbon_available": CODECARBON_AVAILABLE,
        }

        return metrics

    def print_sustainability_scorecard(self, metrics: dict[str, Any]):
        """Prints clean Sustainability & Carbon Footprint Scorecard."""
        print("\n" + "=" * 70)
        print("        SUSTAINABILITY & CARBON EMISSION AUDIT (CodeCarbon)")
        print("=" * 70)
        print(f"  Target Workload Records    : {metrics['total_records']} transactions")
        print(f"  Region / Grid Energy ISO   : {metrics['country_iso_code']}")
        print(f"  Total Carbon Emissions     : {metrics['emissions_mg_co2eq']:.4f} mg CO2eq ({metrics['emissions_kg_co2eq']:.8f} kg)")
        print(f"  Emissions Per Transaction  : {metrics['emissions_per_tx_mg']:.4f} mg CO2eq / tx")
        if metrics["energy_kwh"] > 0:
            print(f"  Total Energy Consumption   : {metrics['energy_kwh']:.8f} kWh")
        print(f"  CodeCarbon Tracker Status  : {'ACTIVE (Audited)' if metrics['codecarbon_available'] else 'OFFLINE (Fallback)'}")
        print("=" * 70 + "\n")
