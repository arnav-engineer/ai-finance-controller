import json
import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Tuple


class SyntheticDataGenerator:
    """
    Generates synthetic multi-source financial datasets with seeded ground-truth labels
    for reconciliation evaluation.
    
    Generates ~200 total records across 3 sources:
      1. GATEWAY (Razorpay API schema shaped)
      2. BANK (Bank statement schema)
      3. LEDGER (Internal ERP/Merchant ledger schema)
    """

    def __init__(self, seed: int = 42):
        random.seed(seed)
        self.base_time = datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc)

    def _random_amount(self) -> float:
        """Generates realistic transaction amounts in INR (₹100 to ₹50,000)."""
        return round(random.uniform(150.0, 48000.0), 2)

    def generate_batch(
        self, batch_id: str = "batch_001", total_records: int = 200
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Generates a batch of ~total_records multi-source entries.
        
        Returns:
            records: List of normalized record dicts ready for raw_records table ingestion.
            eval_manifest: Ground truth summary map for evaluation harness.
        """
        records: List[Dict[str, Any]] = []
        eval_manifest: Dict[str, Any] = {
            "batch_id": batch_id,
            "ground_truth_matches": {},
            "ground_truth_exceptions": {},
        }

        record_counter = 1

        # Breakdown allocation for ~200 records across sources:
        # 1. Clean 1:1 Happy Path Matches (~45 pairs = 90 records)
        # 2. Clean 1:1:1 Triplet Matches (~15 triplets = 45 records)
        # 3. Systemic Cluster A: UTC to IST Time Offset (+5h 30m) (6 pairs = 12 records)
        # 4. Systemic Cluster B: 2% + ₹3 Fee Mismatch (6 pairs = 12 records)
        # 5. Systemic Cluster C: Many-to-One Bank Settlement Payout (1 Bank UTR vs 8 Gateway records = 9 records)
        # 6. Seeded Edge Exceptions (Singletons / Mismatches / Duplicates = 22 records)
        # Total = 90 + 45 + 12 + 12 + 9 + 22 = 190-200 records.

        # --- 1. Clean 1:1 Gateway <-> Bank Matches (45 pairs = 90 records) ---
        for i in range(45):
            gt_id = f"GT_HAPPY_1to1_{i+1:03d}"
            amount = self._random_amount()
            order_id = f"order_hp_{i+1:04d}"
            pay_id = f"pay_{uuid.uuid4().hex[:10]}"
            utr = f"UTR{random.randint(1000000000, 9999999999)}"
            tx_time = self.base_time + timedelta(minutes=i * 15 + random.randint(1, 5))
            tx_time_str = tx_time.isoformat()

            # Gateway Record
            rec_gw = {
                "record_id": f"REC_{record_counter:04d}",
                "batch_id": batch_id,
                "source_type": "GATEWAY",
                "external_id": pay_id,
                "reference_id": order_id,
                "amount": amount,
                "currency": "INR",
                "fee": round(amount * 0.02, 2),
                "tax": round(amount * 0.02 * 0.18, 2),
                "timestamp": tx_time_str,
                "status": "UNMATCHED",
                "raw_data": {
                    "payment_id": pay_id,
                    "order_id": order_id,
                    "method": random.choice(["card", "upi", "netbanking"]),
                    "utr": utr,
                    "gateway": "Razorpay",
                },
                "gt_match_id": gt_id,
                "gt_exception_type": None,
            }
            record_counter += 1

            # Bank Record
            rec_bk = {
                "record_id": f"REC_{record_counter:04d}",
                "batch_id": batch_id,
                "source_type": "BANK",
                "external_id": utr,
                "reference_id": order_id,
                "amount": amount,
                "currency": "INR",
                "fee": 0.0,
                "tax": 0.0,
                "timestamp": (tx_time + timedelta(seconds=random.randint(5, 60))).isoformat(),
                "status": "UNMATCHED",
                "raw_data": {
                    "utr": utr,
                    "description": f"CMS/RAZORPAY/{order_id}/{utr}",
                    "bank_name": "HDFC Bank",
                    "entry_type": "CREDIT",
                },
                "gt_match_id": gt_id,
                "gt_exception_type": None,
            }
            record_counter += 1

            records.extend([rec_gw, rec_bk])
            eval_manifest["ground_truth_matches"][gt_id] = [rec_gw["record_id"], rec_bk["record_id"]]

        # --- 2. Clean 1:1:1 Triplets (Gateway <-> Bank <-> Ledger) (15 triplets = 45 records) ---
        for i in range(15):
            gt_id = f"GT_HAPPY_1to1to1_{i+1:03d}"
            amount = self._random_amount()
            order_id = f"order_triplet_{i+1:04d}"
            pay_id = f"pay_{uuid.uuid4().hex[:10]}"
            utr = f"UTR{random.randint(1000000000, 9999999999)}"
            ledger_id = f"LEDGER_{i+1:04d}"
            tx_time = self.base_time + timedelta(hours=12, minutes=i * 20)

            rec_gw = {
                "record_id": f"REC_{record_counter:04d}",
                "batch_id": batch_id,
                "source_type": "GATEWAY",
                "external_id": pay_id,
                "reference_id": order_id,
                "amount": amount,
                "currency": "INR",
                "fee": round(amount * 0.02, 2),
                "tax": round(amount * 0.02 * 0.18, 2),
                "timestamp": tx_time.isoformat(),
                "status": "UNMATCHED",
                "raw_data": {"payment_id": pay_id, "order_id": order_id, "utr": utr},
                "gt_match_id": gt_id,
                "gt_exception_type": None,
            }
            record_counter += 1

            rec_bk = {
                "record_id": f"REC_{record_counter:04d}",
                "batch_id": batch_id,
                "source_type": "BANK",
                "external_id": utr,
                "reference_id": order_id,
                "amount": amount,
                "currency": "INR",
                "fee": 0.0,
                "tax": 0.0,
                "timestamp": (tx_time + timedelta(seconds=random.randint(10, 120))).isoformat(),
                "status": "UNMATCHED",
                "raw_data": {"utr": utr, "description": f"NEFT-RAZORPAY-{order_id}"},
                "gt_match_id": gt_id,
                "gt_exception_type": None,
            }
            record_counter += 1

            rec_ld = {
                "record_id": f"REC_{record_counter:04d}",
                "batch_id": batch_id,
                "source_type": "LEDGER",
                "external_id": ledger_id,
                "reference_id": order_id,
                "amount": amount,
                "currency": "INR",
                "fee": 0.0,
                "tax": 0.0,
                "timestamp": tx_time.isoformat(),
                "status": "UNMATCHED",
                "raw_data": {"ledger_id": ledger_id, "order_id": order_id, "account": "1001-Sales"},
                "gt_match_id": gt_id,
                "gt_exception_type": None,
            }
            record_counter += 1

            records.extend([rec_gw, rec_bk, rec_ld])
            eval_manifest["ground_truth_matches"][gt_id] = [
                rec_gw["record_id"],
                rec_bk["record_id"],
                rec_ld["record_id"],
            ]

        # --- 3. Systemic Cluster A: Time Offset (+5 hours 30 mins) (6 pairs = 12 records) ---
        for i in range(6):
            gt_id = f"GT_CLUSTER_TIMEOFFSET_{i+1:02d}"
            amount = self._random_amount()
            order_id = f"order_timeoff_{i+1:03d}"
            pay_id = f"pay_{uuid.uuid4().hex[:10]}"
            utr = f"UTR_TIMEOFF_{i+1:03d}"
            gw_time = self.base_time + timedelta(days=1, hours=i * 2)
            # Bank timestamp shifted by IST offset (+5 hours 30 mins = 19800 seconds)
            bk_time = gw_time + timedelta(hours=5, minutes=30)

            rec_gw = {
                "record_id": f"REC_{record_counter:04d}",
                "batch_id": batch_id,
                "source_type": "GATEWAY",
                "external_id": pay_id,
                "reference_id": order_id,
                "amount": amount,
                "currency": "INR",
                "fee": 0.0,
                "tax": 0.0,
                "timestamp": gw_time.isoformat(),
                "status": "UNMATCHED",
                "raw_data": {"payment_id": pay_id, "order_id": order_id, "timezone": "UTC"},
                "gt_match_id": gt_id,
                "gt_exception_type": "TIME_OFFSET",
            }
            record_counter += 1

            rec_bk = {
                "record_id": f"REC_{record_counter:04d}",
                "batch_id": batch_id,
                "source_type": "BANK",
                "external_id": utr,
                "reference_id": order_id,
                "amount": amount,
                "currency": "INR",
                "fee": 0.0,
                "tax": 0.0,
                "timestamp": bk_time.isoformat(),
                "status": "UNMATCHED",
                "raw_data": {"utr": utr, "description": f"RAZORPAY-{order_id}", "timezone": "IST"},
                "gt_match_id": gt_id,
                "gt_exception_type": "TIME_OFFSET",
            }
            record_counter += 1

            records.extend([rec_gw, rec_bk])
            eval_manifest["ground_truth_matches"][gt_id] = [rec_gw["record_id"], rec_bk["record_id"]]

        # --- 4. Systemic Cluster B: Percentage Fee Deduction (2% + ₹3 Flat) (6 pairs = 12 records) ---
        for i in range(6):
            gt_id = f"GT_CLUSTER_FEE_{i+1:02d}"
            gw_amount = self._random_amount()
            fee = round(gw_amount * 0.02 + 3.0, 2)
            bank_net_amount = round(gw_amount - fee, 2)
            order_id = f"order_fee_{i+1:03d}"
            pay_id = f"pay_{uuid.uuid4().hex[:10]}"
            utr = f"UTR_FEE_{i+1:03d}"
            tx_time = self.base_time + timedelta(days=2, hours=i * 3)

            rec_gw = {
                "record_id": f"REC_{record_counter:04d}",
                "batch_id": batch_id,
                "source_type": "GATEWAY",
                "external_id": pay_id,
                "reference_id": order_id,
                "amount": gw_amount,
                "currency": "INR",
                "fee": fee,
                "tax": 0.0,
                "timestamp": tx_time.isoformat(),
                "status": "UNMATCHED",
                "raw_data": {"payment_id": pay_id, "order_id": order_id, "gross_amount": gw_amount},
                "gt_match_id": gt_id,
                "gt_exception_type": "FEE_MISMATCH",
            }
            record_counter += 1

            rec_bk = {
                "record_id": f"REC_{record_counter:04d}",
                "batch_id": batch_id,
                "source_type": "BANK",
                "external_id": utr,
                "reference_id": order_id,
                "amount": bank_net_amount,  # Net amount deposited
                "currency": "INR",
                "fee": 0.0,
                "tax": 0.0,
                "timestamp": (tx_time + timedelta(minutes=10)).isoformat(),
                "status": "UNMATCHED",
                "raw_data": {"utr": utr, "description": f"RZP-NET-CREDIT-{order_id}", "net_credited": bank_net_amount},
                "gt_match_id": gt_id,
                "gt_exception_type": "FEE_MISMATCH",
            }
            record_counter += 1

            records.extend([rec_gw, rec_bk])
            eval_manifest["ground_truth_matches"][gt_id] = [rec_gw["record_id"], rec_bk["record_id"]]

        # --- 5. Systemic Cluster C: Many-to-One Settlement (8 Gateway Payments -> 1 Bank Payout) (9 records) ---
        gt_id_m1 = "GT_CLUSTER_MANY_TO_ONE_01"
        settlement_id = "set_razorpay_batch_88"
        payout_utr = "UTR_SETTLEMENT_BATCH_88"
        batch_gw_records = []
        total_batch_amount = 0.0
        settlement_time = self.base_time + timedelta(days=3)

        for i in range(8):
            gw_amt = round(1000.0 + i * 250.0, 2)
            total_batch_amount += gw_amt
            pay_id = f"pay_m1_{i+1:02d}"
            order_id = f"order_m1_{i+1:02d}"

            rec_gw = {
                "record_id": f"REC_{record_counter:04d}",
                "batch_id": batch_id,
                "source_type": "GATEWAY",
                "external_id": pay_id,
                "reference_id": order_id,
                "amount": gw_amt,
                "currency": "INR",
                "fee": round(gw_amt * 0.02, 2),
                "tax": 0.0,
                "timestamp": (settlement_time - timedelta(hours=i * 2)).isoformat(),
                "status": "UNMATCHED",
                "raw_data": {"payment_id": pay_id, "settlement_id": settlement_id, "order_id": order_id},
                "gt_match_id": gt_id_m1,
                "gt_exception_type": "MANY_TO_ONE",
            }
            record_counter += 1
            batch_gw_records.append(rec_gw["record_id"])
            records.append(rec_gw)

        # Total fee for batch = 2%
        total_batch_fee = round(total_batch_amount * 0.02, 2)
        net_bank_payout = round(total_batch_amount - total_batch_fee, 2)

        rec_bk_settle = {
            "record_id": f"REC_{record_counter:04d}",
            "batch_id": batch_id,
            "source_type": "BANK",
            "external_id": payout_utr,
            "reference_id": settlement_id,
            "amount": net_bank_payout,
            "currency": "INR",
            "fee": 0.0,
            "tax": 0.0,
            "timestamp": settlement_time.isoformat(),
            "status": "UNMATCHED",
            "raw_data": {
                "utr": payout_utr,
                "settlement_id": settlement_id,
                "description": f"RAZORPAY-SETTLEMENT-{settlement_id}-NET-{net_bank_payout}",
            },
            "gt_match_id": gt_id_m1,
            "gt_exception_type": "MANY_TO_ONE",
        }
        record_counter += 1
        records.append(rec_bk_settle)
        eval_manifest["ground_truth_matches"][gt_id_m1] = batch_gw_records + [rec_bk_settle["record_id"]]

        # --- 6. Seeded Edge Exceptions & Singletons (~22 records) ---

        # A. Amount Out of Tolerance (3 pairs = 6 records)
        for i in range(3):
            rec_id_a = f"REC_{record_counter:04d}"
            record_counter += 1
            rec_id_b = f"REC_{record_counter:04d}"
            record_counter += 1
            order_id = f"order_amt_mismatch_{i+1}"
            gw_amt = 5000.0 + i * 1000.0
            bk_amt = gw_amt - 450.0  # Significant mismatch beyond tolerance

            rec_gw = {
                "record_id": rec_id_a,
                "batch_id": batch_id,
                "source_type": "GATEWAY",
                "external_id": f"pay_err_amt_{i+1}",
                "reference_id": order_id,
                "amount": gw_amt,
                "currency": "INR",
                "fee": 0.0,
                "tax": 0.0,
                "timestamp": self.base_time.isoformat(),
                "status": "UNMATCHED",
                "raw_data": {"order_id": order_id},
                "gt_match_id": None,
                "gt_exception_type": "AMOUNT_OUT_OF_TOLERANCE",
            }
            rec_bk = {
                "record_id": rec_id_b,
                "batch_id": batch_id,
                "source_type": "BANK",
                "external_id": f"UTR_ERR_AMT_{i+1}",
                "reference_id": order_id,
                "amount": bk_amt,
                "currency": "INR",
                "fee": 0.0,
                "tax": 0.0,
                "timestamp": self.base_time.isoformat(),
                "status": "UNMATCHED",
                "raw_data": {"order_id": order_id},
                "gt_match_id": None,
                "gt_exception_type": "AMOUNT_OUT_OF_TOLERANCE",
            }
            records.extend([rec_gw, rec_bk])
            eval_manifest["ground_truth_exceptions"][rec_id_a] = "AMOUNT_OUT_OF_TOLERANCE"
            eval_manifest["ground_truth_exceptions"][rec_id_b] = "AMOUNT_OUT_OF_TOLERANCE"

        # B. Missing / Malformed Reference ID (3 pairs = 6 records)
        for i in range(3):
            rec_id_a = f"REC_{record_counter:04d}"
            record_counter += 1
            rec_id_b = f"REC_{record_counter:04d}"
            record_counter += 1
            amt = 2500.0 + i * 500.0

            rec_gw = {
                "record_id": rec_id_a,
                "batch_id": batch_id,
                "source_type": "GATEWAY",
                "external_id": f"pay_missing_ref_{i+1}",
                "reference_id": f"order_valid_{i+1}",
                "amount": amt,
                "currency": "INR",
                "fee": 0.0,
                "tax": 0.0,
                "timestamp": self.base_time.isoformat(),
                "status": "UNMATCHED",
                "raw_data": {"order_id": f"order_valid_{i+1}"},
                "gt_match_id": None,
                "gt_exception_type": "MISSING_REF",
            }
            rec_bk = {
                "record_id": rec_id_b,
                "batch_id": batch_id,
                "source_type": "BANK",
                "external_id": f"UTR_CORRUPTED_{i+1}",
                "reference_id": None,  # Reference id lost/corrupted in bank narration
                "amount": amt,
                "currency": "INR",
                "fee": 0.0,
                "tax": 0.0,
                "timestamp": self.base_time.isoformat(),
                "status": "UNMATCHED",
                "raw_data": {"description": "DIRECT DEPOSIT GARBLED NARRATION"},
                "gt_match_id": None,
                "gt_exception_type": "MISSING_REF",
            }
            records.extend([rec_gw, rec_bk])
            eval_manifest["ground_truth_exceptions"][rec_id_a] = "MISSING_REF"
            eval_manifest["ground_truth_exceptions"][rec_id_b] = "MISSING_REF"

        # C. Duplicate Entry (1 Gateway duplicate pair = 2 records)
        rec_id_dup1 = f"REC_{record_counter:04d}"
        record_counter += 1
        rec_id_dup2 = f"REC_{record_counter:04d}"
        record_counter += 1

        rec_gw1 = {
            "record_id": rec_id_dup1,
            "batch_id": batch_id,
            "source_type": "GATEWAY",
            "external_id": "pay_dup_001",
            "reference_id": "order_dup_001",
            "amount": 7500.0,
            "currency": "INR",
            "fee": 0.0,
            "tax": 0.0,
            "timestamp": self.base_time.isoformat(),
            "status": "UNMATCHED",
            "raw_data": {"note": "original"},
            "gt_match_id": None,
            "gt_exception_type": "DUPLICATE_ENTRY",
        }
        rec_gw2 = {
            "record_id": rec_id_dup2,
            "batch_id": batch_id,
            "source_type": "GATEWAY",
            "external_id": "pay_dup_001",  # Same external ID
            "reference_id": "order_dup_001",
            "amount": 7500.0,
            "currency": "INR",
            "fee": 0.0,
            "tax": 0.0,
            "timestamp": self.base_time.isoformat(),
            "status": "UNMATCHED",
            "raw_data": {"note": "accidental duplicate export retry"},
            "gt_match_id": None,
            "gt_exception_type": "DUPLICATE_ENTRY",
        }
        records.extend([rec_gw1, rec_gw2])
        eval_manifest["ground_truth_exceptions"][rec_id_dup1] = "DUPLICATE_ENTRY"
        eval_manifest["ground_truth_exceptions"][rec_id_dup2] = "DUPLICATE_ENTRY"

        # D. True Unresolvable Singletons (18 records to reach exactly 200 records)
        for i in range(18):
            rec_id_sing = f"REC_{record_counter:04d}"
            record_counter += 1
            source = random.choice(["GATEWAY", "BANK", "LEDGER"])

            rec_sing = {
                "record_id": rec_id_sing,
                "batch_id": batch_id,
                "source_type": source,
                "external_id": f"EXT_ORPHAN_{i+1:02d}",
                "reference_id": f"REF_ORPHAN_{i+1:02d}",
                "amount": self._random_amount(),
                "currency": "INR",
                "fee": 0.0,
                "tax": 0.0,
                "timestamp": (self.base_time + timedelta(days=random.randint(1, 4))).isoformat(),
                "status": "UNMATCHED",
                "raw_data": {"orphan_source": source, "reason": "unmatched bank charge or cancelled order"},
                "gt_match_id": None,
                "gt_exception_type": "TRUE_SINGLETON",
            }
            records.append(rec_sing)
            eval_manifest["ground_truth_exceptions"][rec_id_sing] = "TRUE_SINGLETON"

        return records, eval_manifest


if __name__ == "__main__":
    generator = SyntheticDataGenerator()
    records, eval_manifest = generator.generate_batch("batch_200", total_records=200)

    print(f"Generated {len(records)} synthetic records for evaluation.")
    print("Breakdown by Source:")
    sources = {}
    for r in records:
        s = r["source_type"]
        sources[s] = sources.get(s, 0) + 1
    for s, c in sources.items():
        print(f"  - {s}: {c} records")

    print("\nGround Truth Summary:")
    print(f"  - Clean Match Groups: {len(eval_manifest['ground_truth_matches'])}")
    print(f"  - Flagged Exception Singletons/Clusters: {len(eval_manifest['ground_truth_exceptions'])}")

    # Write synthetic records to file
    with open("data_batch_200.json", "w") as f:
        json.dump({"records": records, "eval_manifest": eval_manifest}, f, indent=2)
    print("\nSaved synthetic dataset to 'data_batch_200.json'")
