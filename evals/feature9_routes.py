"""Feature 9: serve saved evaluation results without rerunning evaluations."""
from __future__ import annotations

import json
from pathlib import Path
from flask import jsonify


def register_feature9_routes(app):
    results_dir = Path(__file__).resolve().parent / "results"

    @app.get("/api/evals")
    def feature9_evals():
        paths = sorted(results_dir.glob("eval_results_*.json"), reverse=True)
        history = []
        latest = None
        for path in paths[:30]:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    continue
                stats = data.get("statistics") or {}
                results = data.get("results") or []
                if not isinstance(stats, dict) or not isinstance(results, list):
                    continue
                history.append({
                    "timestamp": data.get("timestamp"),
                    "average_overall": stats.get("average_overall"),
                    "total_evaluations": stats.get("total_evaluations", len(results)),
                    "filename": path.name,
                })
                if latest is None:
                    latest = data
            except (OSError, UnicodeError, ValueError, TypeError):
                app.logger.warning("Skipping unreadable evaluation result: %s", path)

        if latest is None:
            return jsonify(
                status="not_run", latest=None, results=[], history=[],
                message="No saved evaluation results found. Run python evals/run_evals.py from the project root.",
            )
        return jsonify(
            status="ok",
            latest=latest.get("statistics") or {},
            results=latest.get("results") or [],
            history=history,
            timestamp=latest.get("timestamp"),
            method=latest.get("method"),
            note=latest.get("note"),
        )
