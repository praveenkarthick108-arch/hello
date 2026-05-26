"""
EvaluationRunner — orchestrates all eval suites and generates a combined report.

Usage (standalone, after pipeline completes):

    from evals.eval_runner import EvaluationRunner

    runner = EvaluationRunner(run_ragas=True, run_deepeval=True, output_dir="./eval_reports")
    report = runner.evaluate(state, save_report=True)
    runner.print_report(report)

Usage (integrated into FastAPI endpoint or LangGraph node):

    runner = EvaluationRunner(run_ragas=False, run_deepeval=False)  # basic only, no API cost
    report = runner.evaluate(state)
    if report["summary"]["overall_pass_rate"] < 0.7:
        logger.warning("Trip plan failed eval threshold — consider retry.")
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from evals.basic_evals import BasicEvalSuite, EvalResult
from evals.ragas_evals import RAGASEvaluator
from evals.deepeval_evals import DeepEvalSuite

logger = logging.getLogger(__name__)


class EvaluationRunner:
    """
    Runs basic, RAGAS, and/or DeepEval suites on a completed TripPlannerState dict.

    Args:
        run_basic    : Always run fast deterministic checks (default True).
        run_ragas    : Run RAGAS faithfulness + relevancy (requires ragas + OpenAI key).
        run_deepeval : Run DeepEval metrics (requires deepeval + OpenAI key).
        deepeval_model : OpenAI model id used by DeepEval metrics (default gpt-4o-mini).
        output_dir   : If set, save JSON report here after each evaluate() call.
    """

    def __init__(
        self,
        run_basic: bool = True,
        run_ragas: bool = True,
        run_deepeval: bool = True,
        deepeval_model: str = "gpt-4o-mini",
        output_dir: Optional[str] = None,
    ) -> None:
        self._basic = BasicEvalSuite() if run_basic else None
        self._ragas = RAGASEvaluator() if run_ragas else None
        self._deepeval = DeepEvalSuite(model=deepeval_model) if run_deepeval else None
        self.output_dir = Path(output_dir) if output_dir else None

    # ── Public interface ──────────────────────────────────────────────────────

    def evaluate(self, state: dict, save_report: bool = False) -> dict:
        """Run all enabled suites. Returns a combined report dict."""
        session_id = state.get("session_id", "unknown")
        timestamp = datetime.now(timezone.utc).isoformat()

        report: dict = {
            "session_id": session_id,
            "timestamp": timestamp,
            "suites": {},
        }

        if self._basic:
            logger.info(f"[EvalRunner] basic evals — session {session_id}")
            report["suites"]["basic"] = self._run_safe(self._basic.run, state, "basic")

        if self._ragas:
            logger.info(f"[EvalRunner] RAGAS evals — session {session_id}")
            report["suites"]["ragas"] = self._run_safe(self._ragas.evaluate, state, "ragas")

        if self._deepeval:
            logger.info(f"[EvalRunner] DeepEval evals — session {session_id}")
            report["suites"]["deepeval"] = self._run_safe(self._deepeval.evaluate, state, "deepeval")

        report["summary"] = self._compute_summary(report["suites"])

        if save_report and self.output_dir:
            self._save_report(report, session_id)

        return report

    def evaluate_input_guardrail(self, state: dict) -> dict:
        """Run the DeepEval toxicity + bias check on the raw user input only."""
        if self._deepeval:
            return self._run_safe(self._deepeval.evaluate_guardrail, state, "deepeval_guardrail")
        return {"error": "DeepEval suite not enabled."}

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _run_safe(fn, state: dict, suite_name: str) -> dict:
        try:
            return fn(state)
        except Exception as exc:
            logger.error(f"[EvalRunner] Suite '{suite_name}' crashed: {exc}")
            return {"suite": suite_name, "error": str(exc)}

    @staticmethod
    def _compute_summary(suites: dict) -> dict:
        scores: list[float] = []
        pass_rates: list[float] = []
        errors: list[str] = []

        for name, result in suites.items():
            if "error" in result:
                errors.append(f"{name}: {result['error']}")
                continue
            if isinstance(result.get("avg_score"), float):
                scores.append(result["avg_score"])
            if isinstance(result.get("pass_rate"), float):
                pass_rates.append(result["pass_rate"])

        return {
            "overall_avg_score": round(sum(scores) / len(scores), 4) if scores else None,
            "overall_pass_rate": round(sum(pass_rates) / len(pass_rates), 4) if pass_rates else None,
            "suites_run": len(suites),
            "suites_errored": len(errors),
            "errors": errors,
        }

    def _save_report(self, report: dict, session_id: str) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / f"eval_{session_id}.json"
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, default=_json_default)
        logger.info(f"[EvalRunner] Report saved -> {path}")

    # ── Pretty print ──────────────────────────────────────────────────────────

    def print_report(self, report: dict) -> None:
        """Print a human-readable summary to stdout."""
        sep = "=" * 62
        print(f"\n{sep}")
        print(f"  EVALUATION REPORT  —  session: {report['session_id']}")
        print(f"  {report['timestamp']}")
        print(sep)

        summary = report.get("summary", {})
        print(f"\n  Overall avg score : {summary.get('overall_avg_score', 'N/A')}")
        print(f"  Overall pass rate : {summary.get('overall_pass_rate', 'N/A')}")
        print(f"  Suites run        : {summary.get('suites_run', 0)}")
        for err in summary.get("errors", []):
            print(f"  [ERROR] {err}")

        for suite_name, suite in report.get("suites", {}).items():
            print(f"\n  ── {suite_name.upper()} ──")
            if "error" in suite:
                print(f"    ERROR: {suite['error']}")
                continue

            if suite_name == "basic":
                print(f"    Passed  : {suite.get('passed')}/{suite.get('total')}")
                print(f"    Avg     : {suite.get('avg_score')}")
                for r in suite.get("results", []):
                    mark = "✓" if r.passed else "✗"
                    print(f"    [{mark}] {r.name:<35} {r.score:.3f}  {r.reason}")

            elif suite_name == "ragas":
                print(f"    Avg     : {suite.get('avg_score', 'N/A')}")
                for k, v in suite.get("metrics", {}).items():
                    print(f"    {k:<35} {v}")

            elif suite_name in ("deepeval", "deepeval_guardrail"):
                print(f"    Passed  : {suite.get('passed')}/{suite.get('total')}")
                print(f"    Avg     : {suite.get('avg_score', 'N/A')}")
                for k, v in suite.get("metrics", {}).items():
                    mark = "✓" if v.get("passed") else "✗"
                    reason = (v.get("reason") or "")[:80]
                    print(f"    [{mark}] {k:<35} {v.get('score')}  {reason}")

        print(f"\n{sep}\n")


# ── JSON serialisation helper ─────────────────────────────────────────────────

def _json_default(obj):
    if isinstance(obj, EvalResult):
        return obj.__dict__
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    return str(obj)
