"""Feedback loop for three-layer RAG evaluations.

Records genuine evaluation outcomes, summarizes performance, and generates
human-readable improvement recommendations. Missing evaluations are not
silently counted as successful results.
"""

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import LOGS_DIR, RESULTS_DIR, IMPROVEMENT_THRESHOLDS, EVAL_METRICS


METRIC_NAMES = (
    "recall_at_k", "precision_at_k", "mrr", "ndcg",
    "context_recall", "context_precision", "context_relevance",
    "faithfulness", "answer_relevancy", "answer_correctness",
    "semantic_similarity", "overall",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _threshold(name: str, default: float) -> float:
    return float(IMPROVEMENT_THRESHOLDS.get(name, default))


class FeedbackLoop:
    """Collect and summarize RAG evaluation results."""

    def __init__(self):
        self.feedback_log: List[Dict[str, Any]] = []
        self.performance_history: List[Dict[str, Any]] = []

    def log_query(
        self,
        query: str,
        response: Dict,
        evaluation: Optional[Dict] = None,
        user_feedback: Optional[str] = None,
    ):
        """Record a query, its response and any real evaluation results."""
        entry = {
            "log_id": f"log_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}",
            "timestamp": _now(),
            "query": query,
            "response": response,
            "evaluation": evaluation,
            "user_feedback": user_feedback,
        }
        self.feedback_log.append(entry)
        self._save_log_entry(entry)
        return entry

    def _save_log_entry(self, log_entry: Dict):
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        log_file = LOGS_DIR / f"feedback_log_{datetime.now().strftime('%Y%m%d')}.jsonl"
        with log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False, default=str) + "\n")

    def analyze_performance(self, logs: Optional[List[Dict]] = None) -> Dict:
        """Analyze actual evaluations; missing results remain unevaluated."""
        if logs is None:
            logs = self.feedback_log

        categories = defaultdict(lambda: {"total": 0, "passed": 0, "score_sum": 0.0})
        scores = {name: [] for name in METRIC_NAMES}
        evaluated_count = 0
        failed_count = 0
        unevaluated_count = 0

        for log in logs:
            evaluation = log.get("evaluation") or {}
            if not isinstance(evaluation, dict) or not evaluation:
                unevaluated_count += 1
                continue

            # An explicit evaluation error must not count as a measured score.
            if evaluation.get("error") or evaluation.get("status") in ("error", "failed_to_evaluate"):
                failed_count += 1
                continue

            overall = evaluation.get("overall_score")
            if not isinstance(overall, (int, float)) or isinstance(overall, bool):
                unevaluated_count += 1
                continue

            evaluated_count += 1
            category = str(evaluation.get("category", "unknown"))
            stats = categories[category]
            stats["total"] += 1
            stats["score_sum"] += float(overall)
            scores["overall"].append(float(overall))

            # Respect the evaluator's pass flag when provided. Otherwise
            # derive pass/fail from the configured overall threshold.
            overall_threshold = float(EVAL_METRICS.get("overall", {}).get("threshold", 0.7))
            passed = evaluation.get("passed")
            if passed is None:
                passed = float(overall) >= overall_threshold
            if passed is True:
                stats["passed"] += 1

            for layer in ("layer1_retrieval", "layer2_context", "layer3_generation"):
                for metric, value in (evaluation.get(layer) or {}).items():
                    if metric in scores and metric != "overall" and isinstance(value, (int, float)) and not isinstance(value, bool):
                        scores[metric].append(float(value))

            # Support older evaluations with flat metrics, without counting
            # the same metric twice for one evaluation.
            flat = evaluation.get("metrics") or {}
            for metric, value in flat.items():
                if metric in scores and metric != "overall" and isinstance(value, (int, float)) and not isinstance(value, bool):
                    if not any(metric in (evaluation.get(layer) or {}) for layer in ("layer1_retrieval", "layer2_context", "layer3_generation")):
                        scores[metric].append(float(value))

        average_scores = {
            name: round(sum(values) / len(values), 3)
            for name, values in scores.items() if values
        }
        by_category = {}
        for category, stats in categories.items():
            total = stats["total"]
            by_category[category] = {
                "total": total,
                "passed": stats["passed"],
                "pass_rate": round(100 * stats["passed"] / total, 1) if total else 0.0,
                "avg_score": round(stats["score_sum"] / total, 3) if total else 0.0,
            }

        issues = []
        checks = (
            ("faithfulness", "faithfulness_low", 0.5, "low_faithfulness", "critical", "Review answer grounding and source support"),
            ("recall_at_k", "retrieval_recall_low", 0.4, "low_retrieval_recall", "high", "Review retrieval, embeddings and chunking"),
            ("context_precision", "context_precision_low", 0.3, "low_context_precision", "medium", "Review filtering and reranking"),
            ("answer_correctness", "answer_correctness_low", 0.5, "low_answer_correctness", "high", "Review ground truth, prompts and retrieval"),
        )
        for metric, threshold_key, default, issue_type, severity, recommendation in checks:
            threshold = _threshold(threshold_key, default)
            if metric in average_scores and average_scores[metric] < threshold:
                issues.append({
                    "type": issue_type, "severity": severity, "metric": metric,
                    "current": average_scores[metric], "threshold": threshold,
                    "recommendation": recommendation,
                })

        total_queries = len(logs)
        # Error rate refers to evaluation failures and unevaluated queries,
        # not a fabricated pass/fail count.
        error_rate = (failed_count + unevaluated_count) / total_queries if total_queries else 0.0
        error_threshold = _threshold("error_rate_high", 0.2)
        if total_queries and error_rate > error_threshold:
            issues.append({
                "type": "high_error_rate", "severity": "critical",
                "metric": "error_rate", "current": round(error_rate, 3),
                "threshold": error_threshold,
                "recommendation": "Investigate evaluation exceptions and missing results",
            })

        if not total_queries or not evaluated_count:
            health = "no_evaluation_data"
        else:
            health = "needs_improvement" if issues else "good"

        return {
            "timestamp": _now(),
            "total_queries": total_queries,
            "evaluated_queries": evaluated_count,
            "failed_evaluations": failed_count,
            "unevaluated_queries": unevaluated_count,
            "average_scores": average_scores,
            "by_category": by_category,
            "issues": issues,
            "overall_health": health,
        }

    def generate_improvement_report(self, analysis: Dict) -> str:
        """Produce a report safely even when no evaluations are available."""
        analysis = analysis or self.analyze_performance(logs=[])
        lines = [
            "=" * 80,
            "PERFORMANCE ANALYSIS & IMPROVEMENT RECOMMENDATIONS",
            "=" * 80,
            f"Timestamp: {analysis.get('timestamp') or _now()}",
            f"Total Queries: {analysis.get('total_queries', 0)}",
            f"Evaluated Queries: {analysis.get('evaluated_queries', 0)}",
            f"Failed Evaluations: {analysis.get('failed_evaluations', 0)}",
            f"Unevaluated Queries: {analysis.get('unevaluated_queries', 0)}",
            f"Overall Health: {str(analysis.get('overall_health', 'no_evaluation_data')).upper()}",
        ]

        if not analysis.get("evaluated_queries", 0) and not analysis.get("average_scores"):
            lines.append("\nNo valid evaluation results available. Check retrieval, dependencies and ground-truth data.")
        else:
            lines.extend(["\n" + "-" * 80, "AVERAGE SCORES", "-" * 80])
            for metric, score in (analysis.get("average_scores") or {}).items():
                threshold = float(EVAL_METRICS.get(metric, {}).get("threshold", 0.7))
                status = "PASS" if score >= threshold else "BELOW THRESHOLD"
                lines.append(f"  {status}: {metric}: {score:.3f} (threshold: {threshold:.3f})")

            lines.extend(["\n" + "-" * 80, "PERFORMANCE BY CATEGORY", "-" * 80])
            for category, stats in (analysis.get("by_category") or {}).items():
                lines.extend([
                    f"\n  {category}:",
                    f"    Total: {stats.get('total', 0)}",
                    f"    Passed: {stats.get('passed', 0)}",
                    f"    Pass Rate: {stats.get('pass_rate', 0):.1f}%",
                    f"    Avg Score: {stats.get('avg_score', 0):.3f}",
                ])

        issues = analysis.get("issues") or []
        if issues:
            lines.extend(["\n" + "-" * 80, "ISSUES DETECTED", "-" * 80])
            for issue in issues:
                lines.extend([
                    f"\n  {str(issue.get('type', 'unknown')).upper()} (Severity: {issue.get('severity', 'unknown')})",
                    f"     Metric: {issue.get('metric', 'unknown')}",
                    f"     Current: {float(issue.get('current', 0)):.3f}",
                    f"     Threshold: {issue.get('threshold', 'N/A')}",
                    f"     Recommendation: {issue.get('recommendation', 'Review evaluation results')}",
                ])
        elif analysis.get("evaluated_queries", 0):
            lines.append("\nNo threshold violations detected in the available evaluation results.")

        lines.append("\n" + "=" * 80)
        return "\n".join(lines)

    def save_performance_snapshot(self, analysis: Dict):
        """Save performance analysis, including empty-result diagnostics."""
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        path = RESULTS_DIR / f"performance_snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.json"
        with path.open("w", encoding="utf-8") as f:
            json.dump(analysis, f, indent=2, ensure_ascii=False, default=str)
        print(f"Saved performance snapshot: {path}")
        return path


if __name__ == "__main__":
    feedback_loop = FeedbackLoop()
    analysis = feedback_loop.analyze_performance()
    print(feedback_loop.generate_improvement_report(analysis))
