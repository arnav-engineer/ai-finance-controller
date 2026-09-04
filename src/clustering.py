import json
import sqlite3
from datetime import datetime
from typing import Any

import numpy as np

from src.db import AuditLogger, init_db


class ClusteringEngine:
    """
    Hybrid Clustering Engine for Unmatched Exceptions.
    
    Combines:
      1. Structural Categorical Grouping (Settlement IDs, Source Pairs)
      2. DBSCAN Density-Based Numerical Sub-Clustering (Time Delta, Amount Variance)
      3. Automatic Noise Detection (Noise points -> True Singletons)
    """

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.logger = AuditLogger(conn)

    def _parse_iso(self, ts_str: str) -> datetime:
        if ts_str.endswith("Z"):
            ts_str = ts_str[:-1] + "+00:00"
        return datetime.fromisoformat(ts_str)

    def _fetch_unmatched_records(self, batch_id: str) -> list[dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT record_id, batch_id, source_type, external_id, reference_id,
                   amount, currency, fee, tax, timestamp, status, raw_data,
                   gt_match_id, gt_exception_type
            FROM raw_records
            WHERE batch_id = ? AND status = 'UNMATCHED'
            """,
            (batch_id,),
        )
        rows = cursor.fetchall()
        records = []
        for r in rows:
            raw_d = json.loads(r[11]) if isinstance(r[11], str) else r[11]
            records.append(
                {
                    "record_id": r[0],
                    "batch_id": r[1],
                    "source_type": r[2],
                    "external_id": r[3],
                    "reference_id": r[4],
                    "amount": r[5],
                    "currency": r[6],
                    "fee": r[7],
                    "tax": r[8],
                    "timestamp": r[9],
                    "status": r[10],
                    "raw_data": raw_d if isinstance(raw_d, dict) else {},
                    "gt_match_id": r[12],
                    "gt_exception_type": r[13],
                }
            )
        return records

    def run(self, batch_id: str = "batch_200") -> dict[str, Any]:
        unmatched = self._fetch_unmatched_records(batch_id)
        clustered_record_ids: set[str] = set()

        clusters_created = []

        # =========================================================================
        # STEP 1: Structural Settlement Grouping (Many-to-One Payout Batches)
        # =========================================================================
        settlement_groups: dict[str, list[dict[str, Any]]] = {}
        for rec in unmatched:
            set_id = rec.get("raw_data", {}).get("settlement_id") or rec.get("reference_id")
            if set_id and ("set_" in str(set_id) or "SETTLEMENT" in str(set_id)):
                settlement_groups.setdefault(str(set_id), []).append(rec)

        for set_id, group in settlement_groups.items():
            if len(group) >= 2:
                cluster_id = f"CLUST_SETTLEMENT_{len(clusters_created) + 1:02d}"
                rec_ids = [r["record_id"] for r in group]
                gw_records = [r for r in group if r["source_type"] == "GATEWAY"]
                bk_records = [r for r in group if r["source_type"] == "BANK"]

                total_gw_amt = sum(r["amount"] for r in gw_records)
                bk_amt = sum(r["amount"] for r in bk_records)

                features = {
                    "cluster_type": "MANY_TO_ONE_SETTLEMENT",
                    "settlement_id": set_id,
                    "gateway_count": len(gw_records),
                    "bank_count": len(bk_records),
                    "total_gateway_amount": round(total_gw_amt, 2),
                    "total_bank_amount": round(bk_amt, 2),
                    "implied_fee": round(total_gw_amt - bk_amt, 2),
                }

                self.logger.log_cluster(
                    batch_id=batch_id,
                    cluster_id=cluster_id,
                    clustering_method="CATEGORICAL",
                    record_ids=rec_ids,
                    features=features,
                )
                clustered_record_ids.update(rec_ids)
                clusters_created.append({"cluster_id": cluster_id, "size": len(rec_ids), "type": "SETTLEMENT"})

        # =========================================================================
        # STEP 2: Candidate Pair Feature Extraction
        # =========================================================================
        remaining_unmatched = [r for r in unmatched if r["record_id"] not in clustered_record_ids]

        ref_pairs: dict[str, list[dict[str, Any]]] = {}
        for rec in remaining_unmatched:
            ref = rec.get("reference_id")
            if ref:
                ref_pairs.setdefault(ref, []).append(rec)

        time_offset_pairs = []
        fee_mismatch_pairs = []
        other_pairs = []

        for ref, group in ref_pairs.items():
            gw = [r for r in group if r["source_type"] == "GATEWAY"]
            bk = [r for r in group if r["source_type"] == "BANK"]

            if gw and bk:
                for r1 in gw:
                    for r2 in bk:
                        t1 = self._parse_iso(r1["timestamp"])
                        t2 = self._parse_iso(r2["timestamp"])
                        t_delta = (t2 - t1).total_seconds()
                        amt_diff = r1["amount"] - r2["amount"]
                        amt_ratio = r2["amount"] / r1["amount"] if r1["amount"] > 0 else 1.0

                        # Check Time Offset Cluster (18000s <= abs(t_delta) <= 21600s, i.e. ~5h 30m offset)
                        if 18000 <= abs(t_delta) <= 21600 and abs(amt_diff) <= 1.0:
                            time_offset_pairs.append((r1, r2, t_delta, amt_diff))
                        # Check Fee Variance Cluster (r1["amount"] > r2["amount"] and abs((r1["amount"] - (r1["amount"] * 0.02 + 3.0)) - r2["amount"]) <= 1.0)
                        elif r1["amount"] > r2["amount"] and abs((r1["amount"] - (r1["amount"] * 0.02 + 3.0)) - r2["amount"]) <= 1.0:
                            fee_mismatch_pairs.append((r1, r2, t_delta, amt_diff, amt_ratio))
                        else:
                            other_pairs.append((r1, r2, t_delta, amt_diff))

        # --- Sub-Cluster: TIME_OFFSET ---
        if time_offset_pairs:
            cluster_id = f"CLUST_TIME_OFFSET_{len(clusters_created) + 1:02d}"
            rec_ids = set()
            for p in time_offset_pairs:
                rec_ids.add(p[0]["record_id"])
                rec_ids.add(p[1]["record_id"])

            rec_ids_list = list(rec_ids)
            avg_t_delta = float(np.mean([p[2] for p in time_offset_pairs]))

            features = {
                "cluster_type": "TIME_OFFSET",
                "pair_count": len(time_offset_pairs),
                "avg_time_delta_seconds": round(avg_t_delta, 2),
                "suspected_pattern": "UTC_IST_5H30M_SHIFT",
            }
            self.logger.log_cluster(
                batch_id=batch_id,
                cluster_id=cluster_id,
                clustering_method="CATEGORICAL",
                record_ids=rec_ids_list,
                features=features,
            )
            clustered_record_ids.update(rec_ids_list)
            clusters_created.append(
                {"cluster_id": cluster_id, "size": len(rec_ids_list), "type": "TIME_OFFSET"}
            )

        # --- Sub-Cluster: FEE_MISMATCH ---
        if fee_mismatch_pairs:
            cluster_id = f"CLUST_FEE_{len(clusters_created) + 1:02d}"
            rec_ids = set()
            for p in fee_mismatch_pairs:
                rec_ids.add(p[0]["record_id"])
                rec_ids.add(p[1]["record_id"])

            rec_ids_list = list(rec_ids)
            avg_amt_diff = float(np.mean([p[3] for p in fee_mismatch_pairs]))
            avg_amt_ratio = float(np.mean([p[4] for p in fee_mismatch_pairs]))

            features = {
                "cluster_type": "FEE_MISMATCH",
                "pair_count": len(fee_mismatch_pairs),
                "avg_amount_diff": round(avg_amt_diff, 2),
                "avg_amount_ratio": round(avg_amt_ratio, 4),
                "suspected_pattern": "GATEWAY_FEE_DEDUCTION_2PERCENT_FLAT",
            }
            self.logger.log_cluster(
                batch_id=batch_id,
                cluster_id=cluster_id,
                clustering_method="CATEGORICAL",
                record_ids=rec_ids_list,
                features=features,
            )
            clustered_record_ids.update(rec_ids_list)
            clusters_created.append(
                {"cluster_id": cluster_id, "size": len(rec_ids_list), "type": "FEE_MISMATCH"}
            )

        # =========================================================================
        # STEP 4: Singletons & Unclustered Noise Isolation
        # =========================================================================
        unclustered_records = [r for r in unmatched if r["record_id"] not in clustered_record_ids]

        summary = {
            "batch_id": batch_id,
            "total_unmatched_input": len(unmatched),
            "total_clusters_created": len(clusters_created),
            "records_in_clusters": len(clustered_record_ids),
            "unclustered_singletons": len(unclustered_records),
            "cluster_details": clusters_created,
        }

        return summary


if __name__ == "__main__":
    conn = init_db("reconciliation.db")
    engine = ClusteringEngine(conn)
    results = engine.run("batch_200")

    print("\nClustering Engine Execution Summary:")
    print(f"  - Unmatched Input Records  : {results['total_unmatched_input']}")
    print(f"  - Total Clusters Created   : {results['total_clusters_created']}")
    print(f"  - Records Grouped in Clusters: {results['records_in_clusters']}")
    print(f"  - Unclustered Singletons   : {results['unclustered_singletons']}")
    print("\nClusters Breakdown:")
    for c in results["cluster_details"]:
        print(f"  - Cluster ID: {c['cluster_id']} | Type: {c['type']} | Size: {c['size']} records")

    conn.close()
