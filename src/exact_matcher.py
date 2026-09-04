import json
import sqlite3
from datetime import datetime
from typing import Any

from src.db import AuditLogger, init_db


class ExactMatcher:
    """
    Deterministic Exact & Tolerance Matching Engine.
    
    Executes 3 high-confidence deterministic passes:
      1. Exact 1:1 Key & Amount Match (GATEWAY <-> BANK / GATEWAY <-> LEDGER / BANK <-> LEDGER)
      2. Exact 1:1:1 Triplet Match (GATEWAY <-> BANK <-> LEDGER)
      3. Tight Tolerance Match (Amount delta <= ₹1.00 AND Time delta <= 15 minutes)
    """

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.logger = AuditLogger(conn)

    def _parse_iso(self, ts_str: str) -> datetime:
        """Parses ISO timestamp strings into datetime objects."""
        if ts_str.endswith("Z"):
            ts_str = ts_str[:-1] + "+00:00"
        return datetime.fromisoformat(ts_str)

    def _fetch_unmatched_records(self, batch_id: str) -> list[dict[str, Any]]:
        """Fetches all raw records with UNMATCHED status for the batch."""
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
                    "raw_data": json.loads(r[11]) if isinstance(r[11], str) else r[11],
                    "gt_match_id": r[12],
                    "gt_exception_type": r[13],
                }
            )
        return records

    def run(self, batch_id: str = "batch_200") -> dict[str, Any]:
        """
        Executes exact matching pipeline for the specified batch.
        
        Returns:
            summary: Execution stats including total matched records, matches by pass, and remaining unmatched.
        """
        unmatched_records = self._fetch_unmatched_records(batch_id)
        matched_record_ids: set[str] = set()

        stats = {
            "batch_id": batch_id,
            "initial_unmatched": len(unmatched_records),
            "pass1_exact_1to1_matches": 0,
            "pass2_exact_triplet_matches": 0,
            "pass3_tolerance_matches": 0,
            "total_records_matched": 0,
            "remaining_unmatched": 0,
        }

        # Group records by reference_id / UTR keys
        ref_groups: dict[str, list[dict[str, Any]]] = {}
        for rec in unmatched_records:
            ref = rec.get("reference_id")
            utr = rec.get("raw_data", {}).get("utr") if isinstance(rec.get("raw_data"), dict) else None

            key = ref if ref else utr
            if key:
                ref_groups.setdefault(key, []).append(rec)

        # =========================================================================
        # PASS 1: Exact 1:1:1 Triplet Match (Gateway <-> Bank <-> Ledger)
        # =========================================================================
        for key, items in ref_groups.items():
            unmatched_items = [r for r in items if r["record_id"] not in matched_record_ids]
            sources = {r["source_type"]: r for r in unmatched_items}

            if len(sources) == 3 and len(unmatched_items) == 3:
                r_gw = sources.get("GATEWAY")
                r_bk = sources.get("BANK")
                r_ld = sources.get("LEDGER")

                if r_gw and r_bk and r_ld and (r_gw["amount"] == r_bk["amount"] == r_ld["amount"]):
                        rec_ids = [r_gw["record_id"], r_bk["record_id"], r_ld["record_id"]]
                        details = {
                            "match_type": "1_TO_1_TO_1_TRIPLET",
                            "key_used": "reference_id" if r_gw.get("reference_id") else "utr",
                            "key_value": key,
                            "amount": r_gw["amount"],
                            "record_sources": {
                                r_gw["record_id"]: "GATEWAY",
                                r_bk["record_id"]: "BANK",
                                r_ld["record_id"]: "LEDGER",
                            },
                        }
                        self.logger.log_match(
                            batch_id=batch_id,
                            layer="EXACT_MATCHER",
                            rule_name="exact_triplet_match",
                            confidence=1.0,
                            record_ids=rec_ids,
                            details=details,
                            actor="EXACT_MATCHER",
                            event_type="LAYER1_EXACT_MATCH",
                        )
                        matched_record_ids.update(rec_ids)
                        stats["pass2_exact_triplet_matches"] += 1

        # =========================================================================
        # PASS 2: Exact 1:1 Pair Match (Cross-Source Same Reference & Exact Amount)
        # =========================================================================
        for key, items in ref_groups.items():
            unmatched_items = [r for r in items if r["record_id"] not in matched_record_ids]
            if len(unmatched_items) < 2:
                continue

            by_source: dict[str, list[dict[str, Any]]] = {}
            for r in unmatched_items:
                by_source.setdefault(r["source_type"], []).append(r)

            source_pairs = [("GATEWAY", "BANK"), ("GATEWAY", "LEDGER"), ("BANK", "LEDGER")]
            for s1, s2 in source_pairs:
                if s1 in by_source and s2 in by_source:
                    for r1 in list(by_source[s1]):
                        if r1["record_id"] in matched_record_ids:
                            continue
                        for r2 in list(by_source[s2]):
                            if r2["record_id"] in matched_record_ids:
                                continue

                            if r1["amount"] == r2["amount"]:
                                rec_ids = [r1["record_id"], r2["record_id"]]
                                details = {
                                    "match_type": "1_TO_1_EXACT_PAIR",
                                    "key_used": "reference_id" if r1.get("reference_id") else "utr",
                                    "key_value": key,
                                    "amount": r1["amount"],
                                    "source_pair": [r1["source_type"], r2["source_type"]],
                                }
                                self.logger.log_match(
                                    batch_id=batch_id,
                                    layer="EXACT_MATCHER",
                                    rule_name="exact_1to1_key_amount_match",
                                    confidence=1.0,
                                    record_ids=rec_ids,
                                    details=details,
                                    actor="EXACT_MATCHER",
                                    event_type="LAYER1_EXACT_MATCH",
                                )
                                matched_record_ids.update(rec_ids)
                                stats["pass1_exact_1to1_matches"] += 1
                                break

        # =========================================================================
        # PASS 3: Tight Tolerance Match (Amount <= ₹1.00 & Time <= 15m)
        # =========================================================================
        for key, items in ref_groups.items():
            unmatched_items = [r for r in items if r["record_id"] not in matched_record_ids]
            if len(unmatched_items) < 2:
                continue

            for i in range(len(unmatched_items)):
                r1 = unmatched_items[i]
                if r1["record_id"] in matched_record_ids:
                    continue
                for j in range(i + 1, len(unmatched_items)):
                    r2 = unmatched_items[j]
                    if r2["record_id"] in matched_record_ids:
                        continue
                    if r1["source_type"] == r2["source_type"]:
                        continue

                    amount_delta = abs(r1["amount"] - r2["amount"])
                    t1 = self._parse_iso(r1["timestamp"])
                    t2 = self._parse_iso(r2["timestamp"])
                    time_delta_sec = abs((t1 - t2).total_seconds())

                    if amount_delta <= 1.0 and time_delta_sec <= 900:
                        rec_ids = [r1["record_id"], r2["record_id"]]
                        details = {
                            "match_type": "TOLERANCE_PAIR",
                            "key_used": "reference_id" if r1.get("reference_id") else "utr",
                            "key_value": key,
                            "amount_r1": r1["amount"],
                            "amount_r2": r2["amount"],
                            "amount_delta": round(amount_delta, 2),
                            "time_delta_seconds": round(time_delta_sec, 2),
                            "source_pair": [r1["source_type"], r2["source_type"]],
                        }
                        self.logger.log_match(
                            batch_id=batch_id,
                            layer="EXACT_MATCHER",
                            rule_name="tolerance_match",
                            confidence=0.98,
                            record_ids=rec_ids,
                            details=details,
                            actor="EXACT_MATCHER",
                            event_type="LAYER1_TOLERANCE_MATCH",
                        )
                        matched_record_ids.update(rec_ids)
                        stats["pass3_tolerance_matches"] += 1
                        break

        stats["total_records_matched"] = len(matched_record_ids)
        stats["remaining_unmatched"] = stats["initial_unmatched"] - stats["total_records_matched"]

        return stats


if __name__ == "__main__":
    conn = init_db("reconciliation.db")
    matcher = ExactMatcher(conn)
    results = matcher.run("batch_200")

    print("\nExact Matcher Execution Results:")
    print(f"  - Initial Unmatched Records : {results['initial_unmatched']}")
    print(f"  - Pass 1 (Exact 1:1 Pairs)  : {results['pass1_exact_1to1_matches']} matches")
    print(f"  - Pass 2 (Exact Triplets)   : {results['pass2_exact_triplet_matches']} matches")
    print(f"  - Pass 3 (Tolerance Pairs)  : {results['pass3_tolerance_matches']} matches")
    print(f"  - Total Records Matched     : {results['total_records_matched']}")
    print(f"  - Remaining Unmatched       : {results['remaining_unmatched']}")

    logger = AuditLogger(conn)
    batch_summary = logger.get_batch_summary("batch_200")
    print("\nDatabase State After Exact Matcher:")
    for k, v in batch_summary.items():
        print(f"  - {k}: {v}")

    conn.close()
