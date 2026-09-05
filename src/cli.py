import json
import os

from dotenv import load_dotenv

from src.db import AuditLogger, init_db
from src.evaluator import Evaluator

load_dotenv()

try:
    from groq import Groq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False


class HumanInTheLoopCLI:
    """
    Interactive Terminal Interface providing Human-in-the-Loop Approval
    and Proactive Interrogation Chat for the AI Finance Controller.
    """

    def __init__(self, db_file: str = "reconciliation.db"):
        self.db_file = db_file
        self.conn = init_db(db_file)
        self.logger = AuditLogger(self.conn)
        self.api_key = os.getenv("GROQ_API_KEY", "")
        self.groq_client = None

        if GROQ_AVAILABLE and self.api_key and not self.api_key.startswith("gsk_your_"):
            try:
                self.groq_client = Groq(api_key=self.api_key)
            except Exception as e:  # noqa: BLE001
                print(f"Warning: Groq client init failed: {e}")

    def show_pending_hypotheses(self, batch_id: str = "batch_50") -> list[str]:
        """Displays hypotheses for Human-in-the-Loop review and returns list of hypothesis IDs."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT hypothesis_id, hypothesis_type, parameters, cluster_id, match_rate, proven, source, audit_id
            FROM hypotheses
            WHERE batch_id = ?
            """,
            (batch_id,),
        )
        rows = cursor.fetchall()
        if not rows:
            print("\n  [HITL] No hypotheses found for batch.")
            return []

        print("\n" + "=" * 70)
        print(f"        HUMAN-IN-THE-LOOP: SYSTEMIC HYPOTHESIS APPROVAL ({batch_id})")
        print("=" * 70)
        hyp_ids = []
        for idx, r in enumerate(rows, start=1):
            hyp_id, hyp_type, params_json, cluster_id, match_rate, proven, source, _audit_id = r
            hyp_ids.append(hyp_id)
            params = json.loads(params_json) if isinstance(params_json, str) else params_json
            status = "[PROVEN & APPROVED]" if proven else "[PENDING HUMAN REVIEW]"

            print(f"\n  [{idx}] Hypothesis ID: {hyp_id}")
            print(f"      Target Cluster  : {cluster_id}")
            print(f"      Hypothesis Type : {hyp_type}")
            print(f"      Parameters      : {json.dumps(params)}")
            print(f"      Match Resolution: {match_rate * 100:.1f}% cluster records resolved")
            print(f"      Source          : {source}")
            print(f"      Status          : {status}")
        print("=" * 70 + "\n")
        return hyp_ids

    def _normalize_record_id(self, raw_input: str) -> str:
        """Normalizes user input strings into canonical REC_XXXX format."""
        s = raw_input.strip().upper().replace(" ", "_")
        if s.isdigit():
            return f"REC_{int(s):04d}"
        if s.startswith("REC") and not s.startswith("REC_"):
            num_part = s[3:]
            if num_part.isdigit():
                return f"REC_{int(num_part):04d}"
        return s

    def interrogate_record(self, raw_record_id: str):
        """Proactive Interrogation Chat: Explains why a record failed to match using stored audit facts."""
        record_id = self._normalize_record_id(raw_record_id)
        print("\n" + "=" * 70)
        print(f"        PROACTIVE INTERROGATION CHAT: Record {record_id}")
        print("=" * 70)

        history = self.logger.get_record_history(record_id)
        if not history:
            print(f"  [X] No audit history found for record {record_id}.")
            return

        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT source_type, external_id, reference_id, amount, timestamp, status, raw_data FROM raw_records WHERE record_id = ?",
            (record_id,),
        )
        rec_info = cursor.fetchone()

        evidence_payload = {
            "record_id": record_id,
            "record_details": {
                "source": rec_info[0] if rec_info else "UNKNOWN",
                "external_id": rec_info[1] if rec_info else "",
                "reference_id": rec_info[2] if rec_info else "",
                "amount": rec_info[3] if rec_info else 0.0,
                "timestamp": rec_info[4] if rec_info else "",
                "status": rec_info[5] if rec_info else "",
            },
            "audit_trail_events": history,
        }

        print(f"  Record Details: Source={evidence_payload['record_details']['source']}, Amount=₹{evidence_payload['record_details']['amount']}, Ref={evidence_payload['record_details']['reference_id']}")
        print(f"  Status        : {evidence_payload['record_details']['status']}")
        print(f"  Audit Events  : {len(history)} events recorded in audit_log.")

        # Groq API Interrogation Chat
        if self.groq_client:
            prompt = (
                f"You are the AI Finance Controller answering a human operator's question.\n"
                f"Question: Why didn't record {record_id} match in Pass 1?\n"
                f"Stored Audit Evidence (100% Fact Grounding):\n{json.dumps(evidence_payload, indent=2)}\n\n"
                f"Provide a concise, grounded explanation citing exact amounts, keys, and test outcomes."
            )
            try:
                print("\n  [GROQ LLM INTERROGATION CHAT]:")
                candidate_models = ["openai/gpt-oss-120b"]
                res = None
                for model in candidate_models:
                    try:
                        res = self.groq_client.chat.completions.create(
                            model=model,
                            messages=[
                                {"role": "system", "content": "You are a zero-hallucination financial audit assistant."},
                                {"role": "user", "content": prompt},
                            ],
                            temperature=0.1,
                        )
                        break
                    except Exception:
                        continue
                if res:
                    print(f"  {res.choices[0].message.content.strip()}\n")
            except Exception as e:  # noqa: BLE001
                print(f"  [WARNING] LLM chat error: {e}")
        else:
            print("\n  [EVIDENCE SUMMARY]:")
            for evt in history:
                print(f"    - Event {evt['audit_id']} [{evt['event_type']}]: {evt['rule_name']} (Actor: {evt['actor']})")
        print("=" * 70 + "\n")

    def test_custom_human_rule(self, cluster_id: str, fee_percent: float = 0.02, flat_fee: float = 3.0):
        """Allows a human operator to test a custom hypothesis rule live against a cluster."""
        print(f"\n  [HUMAN LIVE RULE TEST] Testing custom rule (fee_percent={fee_percent}, flat_fee={flat_fee}) on {cluster_id}...")
        cursor = self.conn.cursor()
        cursor.execute("SELECT features FROM clusters WHERE cluster_id = ?", (cluster_id,))
        r = cursor.fetchone()
        if not r:
            print(f"  [X] Cluster {cluster_id} not found.")
            return

        features = json.loads(r[0]) if isinstance(r[0], str) else r[0]
        rec_ids = features.get("record_ids", [])
        if not rec_ids:
            cursor.execute("SELECT record_ids FROM audit_log WHERE details LIKE ? AND event_type = 'CLUSTER_CREATED'", (f"%{cluster_id}%",))
            row = cursor.fetchone()
            if row:
                rec_ids = json.loads(row[0])

        placeholders = ",".join("?" for _ in rec_ids)
        cursor.execute(f"SELECT record_id, source_type, amount, reference_id FROM raw_records WHERE record_id IN ({placeholders})", rec_ids)
        recs = cursor.fetchall()

        gw_recs = [r for r in recs if r[1] == "GATEWAY"]
        bk_recs = [r for r in recs if r[1] == "BANK"]

        resolved = 0
        for g in gw_recs:
            for b in bk_recs:
                if g[3] and g[3] == b[3]:
                    expected_net = round(g[2] - (g[2] * fee_percent + flat_fee), 2)
                    if abs(b[2] - expected_net) <= 0.50:
                        resolved += 2

        match_rate = resolved / len(recs) if recs else 0.0
        print(f"  [OK] Live Test Outcome: {resolved}/{len(recs)} records resolved ({match_rate * 100:.1f}% resolution rate).")
        if match_rate >= 0.80:
            print("  [PROVEN] Rule PROVEN! Ready for Human Approval to commit to database.")
        else:
            print("  [REJECTED] Rule failed threshold (requires >= 80.0%).")

    def interactive_menu(self, batch_id: str = "batch_50"):
        """Main Interactive Menu for Human-in-the-Loop Operations."""
        while True:
            print("\n" + "=" * 60)
            print("     AI FINANCE CONTROLLER — HUMAN-IN-THE-LOOP TERMINAL")
            print("=" * 60)
            print("  1. Review & Approve Hypotheses (Human-in-the-Loop)")
            print("  2. Interrogate Record (Proactive Chat Q&A)")
            print("  3. Test Custom Human Rule Live")
            print("  4. View Evaluation Scorecard")
            print("  5. View Unmatched Exception Transactions")
            print("  6. Exit")
            print("=" * 60)

            choice = input("Enter choice (1-6): ").strip()
            if choice == "1":
                hyp_ids = self.show_pending_hypotheses(batch_id)
                user_inp = input("Enter Hypothesis ID or index number (1, 2) to approve (or press Enter to skip): ").strip()
                if user_inp:
                    target_id = user_inp
                    if user_inp.isdigit():
                        idx = int(user_inp) - 1
                        if 0 <= idx < len(hyp_ids):
                            target_id = hyp_ids[idx]
                    self.approve_hypothesis(target_id, batch_id)
            elif choice == "2":
                rec_id = input("Enter Record ID to interrogate (e.g. REC_0045): ").strip()
                if rec_id:
                    self.interrogate_record(rec_id)
            elif choice == "3":
                cid = input("Enter Cluster ID to test rule on (e.g. CLUST_FEE_02): ").strip()
                if cid:
                    self.test_custom_human_rule(cid, fee_percent=0.02, flat_fee=3.0)
            elif choice == "4":
                evaluator = Evaluator(self.conn)
                scorecard = evaluator.evaluate_batch(batch_id)
                evaluator.print_scorecard(scorecard)
            elif choice == "5":
                evaluator = Evaluator(self.conn)
                report = evaluator.evaluate_batch(batch_id)
                unmatched = report.get("unmatched_details", [])
                print("\n" + "=" * 75)
                print("  UNMATCHED EXCEPTION TRANSACTIONS (LINE-BY-LINE DETAIL)")
                print("=" * 75)
                print(f"  {'RECORD ID':<10} | {'SOURCE':<8} | {'AMOUNT (₹)':<12} | {'REF / EXT ID':<20} | {'CATEGORY'}")
                print("  " + "-" * 71)
                for item in unmatched:
                    ref_disp = item['reference_id'] if item['reference_id'] != 'NONE' else item['external_id']
                    print(f"  {item['record_id']:<10} | {item['source']:<8} | ₹{item['amount']:<11.2f} | {ref_disp:<20} | {item['category']}")
                print("=" * 75 + "\n")
            elif choice == "6":
                print("Exiting HITL CLI. Goodbye!")
                break
            else:
                print("Invalid choice. Please enter 1-6.")


if __name__ == "__main__":
    cli = HumanInTheLoopCLI("reconciliation.db")
    cli.interactive_menu("batch_50")
