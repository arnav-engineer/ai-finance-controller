import json
import random
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any


class SyntheticDataGenerator:
    """
    Generates synthetic multi-source financial datasets with seeded ground-truth labels
    for reconciliation evaluation.
    
    Supports dynamic batch sizes (e.g. 50 records, 200 records) across 3 sources:
      1. GATEWAY (Razorpay API schema shaped)
      2. BANK (Bank statement schema)
      3. LEDGER (Internal ERP/Merchant ledger schema)
    """

    def __init__(self, seed: int = 42):
        random.seed(seed)
        self.base_time = datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC)

    def _random_amount(self) -> float:
        """Generates realistic transaction amounts in INR (₹150 to ₹48,000)."""
        return round(random.uniform(150.0, 48000.0), 2)

    def generate_batch(
        self, batch_id: str = "batch_50", total_records: int = 50
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """
        Generates a batch of synthetic multi-source entries.
        
        Returns:
            records: List of normalized record dicts ready for raw_records table ingestion.
            eval_manifest: Ground truth summary map for evaluation harness.
        """
        records: list[dict[str, Any]] = []
        eval_manifest: dict[str, Any] = {
            "batch_id": batch_id,
            "ground_truth_matches": {},
            "ground_truth_exceptions": {},
        }

        record_counter = 1

        # Scale proportions based on target batch size
        if total_records == 50:
            count_1to1 = 12       # 24 records
            count_1to1to1 = 3     # 9 records
            count_timeoff = 2     # 4 records
            count_fee = 2         # 4 records
            count_m1_gw = 3       # 4 records (3 GW + 1 Bank)
            count_singletons = 5  # 5 records -> Total = 50
        elif total_records == 200:
            count_1to1 = 45       # 90 records
            count_1to1to1 = 15    # 45 records
            count_timeoff = 6     # 12 records
            count_fee = 6         # 12 records
            count_m1_gw = 8       # 9 records
            count_singletons = 32 # 32 records -> Total = 200
        else:
            # Dynamic proportional scaling for arbitrary batch sizes (e.g. 10, 80, 100, 150)
            count_1to1 = max(1, int(total_records * 0.20))
            count_1to1to1 = max(1, int(total_records * 0.05)) if total_records >= 20 else 0
            count_timeoff = max(1, int(total_records * 0.03)) if total_records >= 30 else 0
            count_fee = max(1, int(total_records * 0.03)) if total_records >= 30 else 0
            count_m1_gw = max(2, int(total_records * 0.04)) if total_records >= 25 else 0

            m1_total = (count_m1_gw + 1) if count_m1_gw > 0 else 0
            structured_records = (
                (count_1to1 * 2)
                + (count_1to1to1 * 3)
                + (count_timeoff * 2)
                + (count_fee * 2)
                + m1_total
            )

            while structured_records > total_records and count_1to1 > 0:
                count_1to1 -= 1
                structured_records = (
                    (count_1to1 * 2)
                    + (count_1to1to1 * 3)
                    + (count_timeoff * 2)
                    + (count_fee * 2)
                    + m1_total
                )

            count_singletons = max(0, total_records - structured_records)

        # --- 1. Clean 1:1 Gateway <-> Bank Matches ---
        for i in range(count_1to1):
            gt_id = f"GT_HAPPY_1to1_{i+1:03d}"
            amount = self._random_amount()
            order_id = f"order_hp_{i+1:04d}"
            pay_id = f"pay_{uuid.uuid4().hex[:10]}"
            utr = f"UTR{random.randint(1000000000, 9999999999)}"
            tx_time = self.base_time + timedelta(minutes=i * 15 + random.randint(1, 5))

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

        # --- 2. Clean 1:1:1 Triplets (Gateway <-> Bank <-> Ledger) ---
        for i in range(count_1to1to1):
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

        # --- 3. Systemic Cluster A: Time Offset (+5 hours 30 mins) ---
        for i in range(count_timeoff):
            gt_id = f"GT_CLUSTER_TIMEOFFSET_{i+1:02d}"
            amount = self._random_amount()
            order_id = f"order_timeoff_{i+1:03d}"
            pay_id = f"pay_{uuid.uuid4().hex[:10]}"
            utr = f"UTR_TIMEOFF_{i+1:03d}"
            gw_time = self.base_time + timedelta(days=1, hours=i * 2)
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

        # --- 4. Systemic Cluster B: Percentage Fee Deduction (2% + ₹3 Flat) ---
        for i in range(count_fee):
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
                "amount": bank_net_amount,
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

        # --- 5. Systemic Cluster C: Many-to-One Settlement Payout ---
        gt_id_m1 = "GT_CLUSTER_MANY_TO_ONE_01"
        settlement_id = f"set_rzp_{batch_id}"
        payout_utr = f"UTR_SETTLE_{batch_id}"
        batch_gw_records = []
        total_batch_amount = 0.0
        settlement_time = self.base_time + timedelta(days=3)

        for i in range(count_m1_gw):
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

        if count_m1_gw > 0:
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

        # --- 6. Seeded Singletons & Exceptions ---
        for i in range(count_singletons):
            rec_id_sing = f"REC_{record_counter:04d}"
            record_counter += 1
            source = random.choice(["GATEWAY", "BANK", "LEDGER"])
            gt_type = random.choice(
                ["AMOUNT_OUT_OF_TOLERANCE", "MISSING_REF", "DUPLICATE_ENTRY", "TRUE_SINGLETON"]
            )

            rec_sing = {
                "record_id": rec_id_sing,
                "batch_id": batch_id,
                "source_type": source,
                "external_id": f"EXT_ORPHAN_{i+1:02d}",
                "reference_id": f"REF_ORPHAN_{i+1:02d}" if gt_type != "MISSING_REF" else None,
                "amount": self._random_amount(),
                "currency": "INR",
                "fee": 0.0,
                "tax": 0.0,
                "timestamp": (self.base_time + timedelta(days=random.randint(1, 4))).isoformat(),
                "status": "UNMATCHED",
                "raw_data": {"orphan_source": source, "reason": gt_type},
                "gt_match_id": None,
                "gt_exception_type": gt_type,
            }
            records.append(rec_sing)
            eval_manifest["ground_truth_exceptions"][rec_id_sing] = gt_type

        return records, eval_manifest


if __name__ == "__main__":
    generator = SyntheticDataGenerator()
    records, eval_manifest = generator.generate_batch("batch_50", total_records=50)

    print(f"Generated {len(records)} synthetic records for evaluation.")
    with open("data_batch_50.json", "w") as f:
        json.dump({"records": records, "eval_manifest": eval_manifest}, f, indent=2)
    print("Saved 50-record dataset to 'data_batch_50.json'")
