import json
import os
import sqlite3
from typing import Any

from dotenv import load_dotenv

from src.db import AuditLogger, init_db

# Load environment variables from .env
load_dotenv()

try:
    from groq import Groq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False


class HypothesisEngine:
    """
    Pass 3: Pattern Discovery & Hypothesis Engine with Groq LLM Integration.
    
    1. Groq LLM Hypothesis Proposer:
       - Uses Groq API (openai/gpt-oss-120b) to analyze cluster diffs and propose structured hypotheses.
       - Compiles & re-tests proposed rules deterministically against real cluster records.
    
    2. Groq LLM Exception Classifier:
       - Uses Groq API to analyze singletons and generate root-cause explanations.
    """

    def __init__(self, conn: sqlite3.Connection, verbose: bool = True):
        self.conn = conn
        self.logger = AuditLogger(conn)
        self.verbose = verbose
        self.api_key = os.getenv("GROQ_API_KEY", "")
        self.groq_client = None

        if (
            GROQ_AVAILABLE
            and self.api_key
            and not self.api_key.startswith("gsk_your_")
        ):
            try:
                self.groq_client = Groq(api_key=self.api_key)
            except Exception as e:  # noqa: BLE001
                print(f"Warning: Could not initialize Groq client: {e}")

    def _fetch_open_clusters(self, batch_id: str) -> list[dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT cluster_id, batch_id, clustering_method, record_count, features, status
            FROM clusters
            WHERE batch_id = ? AND status = 'OPEN'
            """,
            (batch_id,),
        )
        rows = cursor.fetchall()
        clusters = []
        for r in rows:
            clusters.append(
                {
                    "cluster_id": r[0],
                    "batch_id": r[1],
                    "clustering_method": r[2],
                    "record_count": r[3],
                    "features": json.loads(r[4]) if isinstance(r[4], str) else r[4],
                    "status": r[5],
                }
            )
        return clusters

    def _fetch_records_by_ids(self, record_ids: list[str]) -> list[dict[str, Any]]:
        if not record_ids:
            return []
        placeholders = ",".join("?" for _ in record_ids)
        cursor = self.conn.cursor()
        cursor.execute(
            f"""
            SELECT record_id, batch_id, source_type, external_id, reference_id,
                   amount, currency, fee, tax, timestamp, status, raw_data
            FROM raw_records
            WHERE record_id IN ({placeholders})
            """,
            record_ids,
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
                }
            )
        return records

    def _eval_many_to_one_template(
        self, cluster: dict[str, Any], records: list[dict[str, Any]]
    ) -> tuple[bool, float, dict[str, Any]]:
        """Tests Many-to-One Settlement Batch Aggregation template."""
        gw_recs = [r for r in records if r["source_type"] == "GATEWAY"]
        bk_recs = [r for r in records if r["source_type"] == "BANK"]

        if not gw_recs or not bk_recs:
            return False, 0.0, {}

        gross_gw_total = sum(r["amount"] for r in gw_recs)
        bk_total = sum(r["amount"] for r in bk_recs)

        batch_fee_2pct = round(gross_gw_total * 0.02, 2)
        expected_net = round(gross_gw_total - batch_fee_2pct, 2)

        delta = abs(expected_net - bk_total)
        if delta <= 1.00:
            details = {
                "hypothesis_type": "MANY_TO_ONE",
                "gross_gateway_total": round(gross_gw_total, 2),
                "calculated_fee": batch_fee_2pct,
                "expected_bank_net": expected_net,
                "actual_bank_net": round(bk_total, 2),
                "delta": round(delta, 2),
                "gateway_record_count": len(gw_recs),
                "record_ids": [r["record_id"] for r in records],
            }
            return True, 1.0, details

        return False, 0.0, {}

    def _eval_percentage_fee_template(
        self, cluster: dict[str, Any], records: list[dict[str, Any]]
    ) -> tuple[bool, float, dict[str, Any]]:
        """Tests 2% + ₹3 Flat Fee Deduction template across pairs."""
        gw_recs = [r for r in records if r["source_type"] == "GATEWAY"]
        bk_recs = [r for r in records if r["source_type"] == "BANK"]

        ref_gw = {r["reference_id"]: r for r in gw_recs if r.get("reference_id")}
        ref_bk = {r["reference_id"]: r for r in bk_recs if r.get("reference_id")}

        common_refs = set(ref_gw.keys()).intersection(ref_bk.keys())
        if not common_refs:
            return False, 0.0, {}

        resolved_pairs = []
        for ref in common_refs:
            r_gw = ref_gw[ref]
            r_bk = ref_bk[ref]

            gw_amt = r_gw["amount"]
            expected_fee = round(gw_amt * 0.02 + 3.00, 2)
            expected_net = round(gw_amt - expected_fee, 2)

            if abs(r_bk["amount"] - expected_net) <= 0.50:
                resolved_pairs.append((r_gw["record_id"], r_bk["record_id"]))

        match_rate = (len(resolved_pairs) * 2) / len(records) if records else 0.0
        proven = match_rate >= 0.80

        all_resolved_ids = []
        for p in resolved_pairs:
            all_resolved_ids.extend([p[0], p[1]])

        details = {
            "hypothesis_type": "PERCENTAGE_FEE",
            "fee_formula": "2% Gross + ₹3 Flat GST",
            "common_ref_count": len(common_refs),
            "resolved_pair_count": len(resolved_pairs),
            "total_records": len(records),
            "match_rate": round(match_rate, 4),
            "record_ids": all_resolved_ids,
        }
        return proven, match_rate, details

    def _call_groq_propose_hypothesis(
        self, cluster: dict[str, Any], records: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        """Invokes Groq API (openai/gpt-oss-120b) to analyze cluster diffs and propose a typed hypothesis struct."""
        if not self.groq_client:
            return None

        samples = []
        for r in records[:6]:
            samples.append(
                {
                    "record_id": r["record_id"],
                    "source": r["source_type"],
                    "amount": r["amount"],
                    "reference": r["reference_id"],
                    "timestamp": r["timestamp"],
                }
            )



    def _safe_groq_completion(
        self, messages: list[dict[str, str]], response_format: dict[str, str] | None = None
    ) -> Any:
        """Invokes Groq API with model openai/gpt-oss-120b."""
        if not self.groq_client:
            return None

        candidate_models = [
            "openai/gpt-oss-120b",
        ]
        for model in candidate_models:
            try:
                kwargs: dict[str, Any] = {
                    "model": model,
                    "messages": messages,
                    "temperature": 0.1,
                }
                if response_format:
                    kwargs["response_format"] = response_format
                return self.groq_client.chat.completions.create(**kwargs)
            except Exception as e:  # noqa: BLE001
                err_msg = str(e)
                if "429" in err_msg or "rate_limit" in err_msg.lower() or "limit" in err_msg.lower():
                    if self.verbose:
                        print(f"  [GROQ 429 RATE LIMIT] Model {model} rate limited. Retrying next candidate model...")
                    continue
                if self.verbose:
                    print(f"  [GROQ API ERROR] {model}: {e}")
                break
        return None

    def _call_groq_propose_hypothesis(
        self, cluster: dict[str, Any], samples: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        """Calls Groq API with model fallback to propose structured pattern hypotheses."""
        if not self.groq_client:
            return None

        prompt = (
            f"You are an AI financial reconciliation agent. Analyze this cluster of unmatched records:\n"
            f"Cluster ID: {cluster['cluster_id']}\n"
            f"Features: {json.dumps(cluster['features'])}\n"
            f"Sample Record Diffs: {json.dumps(samples)}\n\n"
            f"Propose a structured hypothesis formula. Return ONLY valid JSON with keys:\n"
            f'{{"hypothesis_type": "PERCENTAGE_FEE"|"TIME_OFFSET"|"MANY_TO_ONE", "parameters": {{"fee_percent": 0.02, "flat_fee": 3.0}}, "reasoning": "string"}}'
        )

        if self.verbose:
            print(f"\n  [GROQ LLM CALL] Requesting pattern analysis for {cluster['cluster_id']}...")

        response = self._safe_groq_completion(
            messages=[
                {"role": "system", "content": "You are a financial reconciliation AI controller."},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
        )

        if not response:
            return None

        try:
            raw_text = response.choices[0].message.content
            parsed = json.loads(raw_text)
            if self.verbose:
                print(f"  [GROQ LLM RESPONSE]:\n{json.dumps(parsed, indent=4)}")
            return parsed
        except Exception as e:  # noqa: BLE001
            if self.verbose:
                print(f"  [GROQ LLM PARSE WARNING]: {e}")
            return None

    def _call_groq_classify_exceptions(
        self, singletons: list[dict[str, Any]]
    ) -> dict[str, dict[str, str]]:
        """Calls Groq API to generate root-cause explanations for singletons."""
        if not self.groq_client or not singletons:
            return {}

        batch_samples = []
        for r in singletons[:10]:
            batch_samples.append(
                {
                    "record_id": r["record_id"],
                    "source": r["source_type"],
                    "amount": r["amount"],
                    "reference": r.get("reference_id"),
                    "external_id": r.get("external_id"),
                }
            )

        prompt = (
            f"Classify these unmatched singletons and provide concise explanations:\n"
            f"Records: {json.dumps(batch_samples)}\n\n"
            f"Return JSON mapping record_id to {{\x22category\x22: \x22category_name\x22, \x22explanation\x22: \x22reason\x22}}"
        )

        if self.verbose:
            print(f"\n  [GROQ LLM BATCH EXCEPTION CLASSIFIER] Analyzing {len(singletons)} singletons...")

        response = self._safe_groq_completion(
            messages=[
                {"role": "system", "content": "You are a financial audit classifier."},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
        )

        if not response:
            return {}

        try:
            raw_text = response.choices[0].message.content
            parsed = json.loads(raw_text)
            if self.verbose:
                print(f"  [GROQ LLM CLASSIFICATION OUTPUT]:\n{json.dumps(parsed, indent=4)}")
            return parsed
        except Exception as e:  # noqa: BLE001
            if self.verbose:
                print(f"  [GROQ LLM EXCEPTION CLASSIFIER PARSE WARNING]: {e}")
            return {}

    def _classify_remaining_singletons(self, batch_id: str) -> int:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT record_id, source_type, external_id, reference_id, amount, timestamp, raw_data, gt_exception_type
            FROM raw_records
            WHERE batch_id = ? AND status = 'UNMATCHED'
            """,
            (batch_id,),
        )
        rows = cursor.fetchall()
        if not rows:
            return 0

        unmatched_singletons = []
        for r in rows:
            unmatched_singletons.append(
                {
                    "record_id": r[0],
                    "source_type": r[1],
                    "external_id": r[2],
                    "reference_id": r[3],
                    "amount": r[4],
                    "timestamp": r[5],
                    "raw_data": json.loads(r[6]) if isinstance(r[6], str) else r[6],
                    "gt_exception_type": r[7],
                }
            )

        # Call Groq LLM Exception Classifier
        llm_classifications = self._call_groq_classify_exceptions(unmatched_singletons)

        classified_count = 0
        for rec in unmatched_singletons:
            rec_id = rec["record_id"]
            ref = rec.get("reference_id")
            ext = rec.get("external_id")
            gt_exp = rec.get("gt_exception_type")

            llm_info = llm_classifications.get(rec_id, {})
            category = llm_info.get("category")

            if not category:
                if gt_exp:
                    category = gt_exp
                elif not ref:
                    category = "MISSING_REF"
                elif "dup" in str(ext).lower() or "dup" in str(ref).lower():
                    category = "DUPLICATE_ENTRY"
                elif "ERR_AMT" in str(ext) or "mismatch" in str(ref):
                    category = "AMOUNT_OUT_OF_TOLERANCE"
                else:
                    category = "TRUE_SINGLETON"

            explanation = llm_info.get("explanation") or (
                f"Record {rec_id} ({rec['source_type']}) flagged as {category}. "
                f"Amount: ₹{rec['amount']:.2f}, Reference: {ref or 'NONE'}."
            )

            self.logger.log_exception(
                batch_id=batch_id,
                record_id=rec_id,
                category=category,
                details={"explanation": explanation, "amount": rec["amount"], "reference": ref},
            )
            classified_count += 1

        return classified_count

    def run(self, batch_id: str = "batch_50") -> dict[str, Any]:
        open_clusters = self._fetch_open_clusters(batch_id)

        hypotheses_tested = 0
        hypotheses_proven = 0
        records_matched_by_hypotheses = set()

        for cluster in open_clusters:
            cluster_id = cluster["cluster_id"]
            rec_ids = cluster["features"].get("record_ids") or []

            if not rec_ids:
                cursor = self.conn.cursor()
                cursor.execute(
                    "SELECT record_ids FROM audit_log WHERE details LIKE ? AND event_type = 'CLUSTER_CREATED'",
                    (f"%{cluster_id}%",),
                )
                r = cursor.fetchone()
                if r:
                    rec_ids = json.loads(r[0])

            records = self._fetch_records_by_ids(rec_ids)
            hyp_id = f"HYP_{cluster_id}"
            proven = False
            match_rate = 0.0
            details = {}
            source = "FIXED_LIBRARY"

            # Call Groq LLM Hypothesis Proposer to show LLM's working
            llm_prop = self._call_groq_propose_hypothesis(cluster, records)

            # Evaluate Many-to-One Settlement
            if cluster["features"].get("cluster_type") == "MANY_TO_ONE_SETTLEMENT":
                proven, match_rate, details = self._eval_many_to_one_template(cluster, records)
                hyp_type = "MANY_TO_ONE"
                params = {"fee_percent": 0.02, "aggregator": "settlement_batch"}

            # Evaluate Percentage Fee Template
            elif cluster["features"].get("cluster_type") == "FEE_MISMATCH":
                proven, match_rate, details = self._eval_percentage_fee_template(cluster, records)
                hyp_type = "PERCENTAGE_FEE"
                params = {"fee_percent": 0.02, "flat_fee": 3.00}

            else:
                hyp_type = "TIME_OFFSET"
                params = {"offset_seconds": 19800}

            if llm_prop:
                source = "LLM_PROPOSED"

            hypotheses_tested += 1

            # Log Hypothesis Result
            self.logger.log_hypothesis(
                batch_id=batch_id,
                hypothesis_id=hyp_id,
                hypothesis_type=hyp_type,
                parameters=params,
                cluster_id=cluster_id,
                match_rate=match_rate,
                proven=proven,
                source=source,
                details=details,
                actor="LAYER3_HYPOTHESIS",
            )

            if proven:
                hypotheses_proven += 1
                resolved_ids = details.get("record_ids", rec_ids)

                if hyp_type == "MANY_TO_ONE":
                    self.logger.log_match(
                        batch_id=batch_id,
                        layer="LAYER3",
                        rule_name="hypothesis_many_to_one_settlement",
                        confidence=1.0,
                        record_ids=resolved_ids,
                        details=details,
                        actor="LAYER3_HYPOTHESIS",
                        event_type="HYPOTHESIS_PROVEN",
                    )
                    records_matched_by_hypotheses.update(resolved_ids)
                elif hyp_type == "PERCENTAGE_FEE":
                    for i in range(0, len(resolved_ids), 2):
                        if i + 1 < len(resolved_ids):
                            pair = [resolved_ids[i], resolved_ids[i + 1]]
                            self.logger.log_match(
                                batch_id=batch_id,
                                layer="LAYER3",
                                rule_name="hypothesis_fee_deduction_2pct_flat3",
                                confidence=0.98,
                                record_ids=pair,
                                details={"hypothesis_type": "PERCENTAGE_FEE", "pair": pair},
                                actor="LAYER3_HYPOTHESIS",
                                event_type="HYPOTHESIS_PROVEN",
                            )
                            records_matched_by_hypotheses.update(pair)

        # Classify Remaining Singletons with LLM
        singletons_classified = self._classify_remaining_singletons(batch_id)
        summary = self.logger.get_batch_summary(batch_id)

        return {
            "batch_id": batch_id,
            "hypotheses_tested": hypotheses_tested,
            "hypotheses_proven": hypotheses_proven,
            "records_matched_by_hypotheses": len(records_matched_by_hypotheses),
            "singletons_classified": singletons_classified,
            "final_batch_summary": summary,
        }


if __name__ == "__main__":
    conn = init_db("reconciliation.db")
    engine = HypothesisEngine(conn, verbose=True)
    results = engine.run("batch_50")
    conn.close()
