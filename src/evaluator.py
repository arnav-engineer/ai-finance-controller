import json
import sqlite3
from typing import Dict, Any, List


class Evaluator:
    """
    Evaluation Harness for AI Finance Controller.
    
    Compares the engine's output (matches and exceptions in SQLite) against
    hidden ground-truth labels (gt_match_id, gt_exception_type) in raw_records.
    
    Generates:
      - Precision (False Positive Rate)
      - Recall / Match Rate
      - Confusion Matrix for Exception Classification
      - Summary Scorecard Report
    """

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def evaluate_batch(self, batch_id: str = "batch_50") -> Dict[str, Any]:
        cursor = self.conn.cursor()

        # 1. Fetch total record count and status breakdown
        cursor.execute("SELECT COUNT(*) FROM raw_records WHERE batch_id = ?", (batch_id,))
        total_records = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM raw_records WHERE batch_id = ? AND status = 'MATCHED'",
            (batch_id,),
        )
        matched_records_count = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM raw_records WHERE batch_id = ? AND status = 'EXCEPTION'",
            (batch_id,),
        )
        exception_records_count = cursor.fetchone()[0]

        # 2. Evaluate Match Precision & Ground-Truth Alignment
        cursor.execute(
            "SELECT match_id, layer, rule_name, confidence, record_ids FROM matches WHERE batch_id = ?",
            (batch_id,),
        )
        match_rows = cursor.fetchall()

        correct_matches = 0
        false_matches = 0
        matched_record_ids_set = set()

        for row in match_rows:
            rec_ids = json.loads(row[4]) if isinstance(row[4], str) else row[4]
            matched_record_ids_set.update(rec_ids)

            placeholders = ",".join("?" for _ in rec_ids)
            cursor.execute(
                f"SELECT gt_match_id FROM raw_records WHERE record_id IN ({placeholders})",
                rec_ids,
            )
            gt_ids = set(r[0] for r in cursor.fetchall())

            # A match is correct if all matched records share the exact same non-None gt_match_id
            if len(gt_ids) == 1 and None not in gt_ids:
                correct_matches += len(rec_ids)
            else:
                false_matches += len(rec_ids)

        # 3. Evaluate Ground-Truth Matchable Total
        cursor.execute(
            "SELECT COUNT(*) FROM raw_records WHERE batch_id = ? AND gt_match_id IS NOT NULL",
            (batch_id,),
        )
        gt_matchable_total = cursor.fetchone()[0]

        precision = (
            (correct_matches / (correct_matches + false_matches))
            if (correct_matches + false_matches) > 0
            else 1.0
        )
        recall = (correct_matches / gt_matchable_total) if gt_matchable_total > 0 else 0.0
        overall_match_rate = matched_records_count / total_records if total_records > 0 else 0.0

        # 4. Evaluate Exception Classification Accuracy
        cursor.execute(
            """
            SELECT e.record_id, e.category, r.gt_exception_type
            FROM exceptions e
            JOIN raw_records r ON e.record_id = r.record_id
            WHERE e.batch_id = ?
            """,
            (batch_id,),
        )
        exc_rows = cursor.fetchall()
        correct_exceptions = 0
        total_exceptions_evaluated = len(exc_rows)
        exception_breakdown = {}

        for r in exc_rows:
            cat = r[1]
            gt_cat = r[2]
            exception_breakdown[cat] = exception_breakdown.get(cat, 0) + 1
            if gt_cat and cat == gt_cat:
                correct_exceptions += 1
            elif not gt_cat and cat == "TRUE_SINGLETON":
                correct_exceptions += 1

        exception_accuracy = (
            (correct_exceptions / total_exceptions_evaluated)
            if total_exceptions_evaluated > 0
            else 1.0
        )

        report = {
            "batch_id": batch_id,
            "total_records": total_records,
            "matched_records": matched_records_count,
            "exception_records": exception_records_count,
            "overall_match_rate": round(overall_match_rate, 4),
            "match_precision": round(precision, 4),
            "match_recall": round(recall, 4),
            "gt_matchable_total": gt_matchable_total,
            "correct_matches": correct_matches,
            "false_matches": false_matches,
            "exception_accuracy": round(exception_accuracy, 4),
            "exception_breakdown": exception_breakdown,
        }

        return report

    def print_scorecard(self, report: Dict[str, Any]):
        """Prints a human-readable evaluation scorecard report."""
        print("\n" + "=" * 65)
        print(f"        RECONCILIATION EVALUATION SCORECARD ({report['batch_id']})")
        print("=" * 65)
        print(f"  Total Ingested Batch Records  : {report['total_records']}")
        print(f"  Successfully Matched Records  : {report['matched_records']}")
        print(f"  Flagged Exception Records     : {report['exception_records']}")
        print(f"  Overall Batch Match Rate      : {report['overall_match_rate'] * 100:.2f}%")
        print("-" * 65)
        print("  ACCURACY & AUDIT METRICS:")
        print(f"  - Match Precision (Target 100%): {report['match_precision'] * 100:.2f}% (False Positives: {report['false_matches']})")
        print(f"  - Match Recall (Ground Truth)  : {report['match_recall'] * 100:.2f}% ({report['correct_matches']}/{report['gt_matchable_total']} GT records)")
        print(f"  - Exception Categorization Acc : {report['exception_accuracy'] * 100:.2f}%")
        print("-" * 65)
        print("  HONEST EXCEPTION LIST BREAKDOWN:")
        for cat, count in report["exception_breakdown"].items():
            print(f"    * {cat:<25}: {count} records")
        print("=" * 65 + "\n")


if __name__ == "__main__":
    conn = sqlite3.connect("reconciliation.db")
    evaluator = Evaluator(conn)
    report = evaluator.evaluate_batch("batch_200")
    evaluator.print_scorecard(report)
    conn.close()
