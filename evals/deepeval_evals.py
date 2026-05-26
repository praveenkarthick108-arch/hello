"""
DeepEval-based evaluation for the trip planner.

Metrics:
  - AnswerRelevancyMetric : Is the itinerary relevant to the user's travel request?
  - FaithfulnessMetric    : Is the itinerary grounded in the retrieved research data?
  - HallucinationMetric   : Does the itinerary invent facts not in any context?
  - GEval (custom)        : Trip-planning quality rubric (activities, budget, structure).

DeepEval is optional — if not installed the suite returns a graceful error dict.
Install with:  pip install deepeval
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from deepeval.metrics import (
        AnswerRelevancyMetric,
        FaithfulnessMetric,
        HallucinationMetric,
        GEval,
    )
    from deepeval.test_case import LLMTestCase, LLMTestCaseParams
    DEEPEVAL_AVAILABLE = True
except ImportError:
    DEEPEVAL_AVAILABLE = False
    logger.warning(
        "deepeval not installed — DeepEvalSuite will return error dicts. pip install deepeval"
    )

from evals.ragas_evals import _itinerary_to_text, _build_contexts


# ── Custom GEval criteria ─────────────────────────────────────────────────────

_TRIP_QUALITY_CRITERIA = (
    "Evaluate whether the trip itinerary is practical, well-structured, "
    "and correctly tailored to the user's stated requirements "
    "(destination, origin, budget, trip duration, number of travelers, and preferences). "
    "The itinerary should cover every day of the trip, include specific activities "
    "with named venues or experiences, list accommodation for each night, "
    "mention meal options, and provide transport notes. Budget estimates must be "
    "present and must not exceed the user's stated budget by more than 10%."
)

_TRIP_QUALITY_STEPS = [
    "Confirm the itinerary destination matches the user's requested destination.",
    "Verify the itinerary covers the full trip duration (all days from start to end date).",
    "Check that each day lists specific, named activities — not vague placeholders.",
    "Confirm accommodation is mentioned for each night.",
    "Check that the total budget estimate does not exceed the stated budget.",
    "Evaluate whether the daily pace is realistic (not too many activities crammed into one day).",
    "Check that transport notes or directions are included for at least the arrival and departure days.",
]


# ── Evaluator ─────────────────────────────────────────────────────────────────

class DeepEvalSuite:
    """
    Runs DeepEval metrics on a single completed trip state.
    Each metric calls the configured LLM via DeepEval's built-in evaluation chain.
    """

    def __init__(self, model: str = "gpt-4o-mini", threshold: float = 0.7):
        self.available = DEEPEVAL_AVAILABLE
        self.model = model
        self.threshold = threshold

    def build_test_case(self, state: dict) -> dict:
        """Return fields needed to build an LLMTestCase."""
        return {
            "input": state.get("raw_input", ""),
            "actual_output": _itinerary_to_text(state),
            "retrieval_context": _build_contexts(state),
        }

    def evaluate(self, state: dict) -> dict:
        """Run all DeepEval metrics on a single trip state."""
        if not self.available:
            return {
                "suite": "deepeval",
                "error": "deepeval not installed. Run: pip install deepeval",
                "metrics": {},
            }

        tc_data = self.build_test_case(state)
        if not tc_data["input"] or not tc_data["actual_output"]:
            return {
                "suite": "deepeval",
                "error": "Insufficient data in state for DeepEval evaluation.",
                "metrics": {},
            }

        test_case = LLMTestCase(
            input=tc_data["input"],
            actual_output=tc_data["actual_output"],
            retrieval_context=tc_data["retrieval_context"],
            context=tc_data["retrieval_context"],
        )

        metric_instances = [
            AnswerRelevancyMetric(
                threshold=self.threshold,
                model=self.model,
                include_reason=True,
            ),
            FaithfulnessMetric(
                threshold=self.threshold,
                model=self.model,
                include_reason=True,
            ),
            HallucinationMetric(
                threshold=self.threshold,
                model=self.model,
                include_reason=True,
            ),
            GEval(
                name="TripPlanningQuality",
                criteria=_TRIP_QUALITY_CRITERIA,
                evaluation_steps=_TRIP_QUALITY_STEPS,
                evaluation_params=[
                    LLMTestCaseParams.INPUT,
                    LLMTestCaseParams.ACTUAL_OUTPUT,
                    LLMTestCaseParams.RETRIEVAL_CONTEXT,
                ],
                model=self.model,
                threshold=self.threshold,
            ),
        ]

        metrics_out: dict[str, dict] = {}
        for metric in metric_instances:
            metric_name = getattr(metric, "name", metric.__class__.__name__)
            try:
                import asyncio
                asyncio.run(metric.a_measure(test_case))
                metrics_out[metric_name] = {
                    "score": round(float(metric.score), 4) if metric.score is not None else None,
                    "passed": metric.is_successful(),
                    "reason": getattr(metric, "reason", None),
                }
            except Exception as exc:
                logger.error(f"[DeepEvalSuite] Metric {metric_name} failed: {exc}")
                metrics_out[metric_name] = {
                    "score": None,
                    "passed": False,
                    "reason": f"Metric error: {exc}",
                }

        scores = [v["score"] for v in metrics_out.values() if v["score"] is not None]
        n_passed = sum(1 for v in metrics_out.values() if v.get("passed"))
        avg_score = round(sum(scores) / len(scores), 4) if scores else 0.0

        return {
            "suite": "deepeval",
            "passed": n_passed,
            "total": len(metric_instances),
            "pass_rate": round(n_passed / len(metric_instances), 3),
            "avg_score": avg_score,
            "metrics": metrics_out,
        }

    def evaluate_guardrail(self, state: dict) -> dict:
        """
        Lightweight toxicity + bias check on the raw user input.
        Useful as an additional LLM-based safety layer.
        """
        if not self.available:
            return {"suite": "deepeval_guardrail", "error": "deepeval not installed.", "metrics": {}}

        raw_input = state.get("raw_input", "")
        if not raw_input:
            return {"suite": "deepeval_guardrail", "error": "No raw_input in state.", "metrics": {}}

        try:
            from deepeval.metrics import ToxicityMetric, BiasMetric
        except ImportError:
            return {
                "suite": "deepeval_guardrail",
                "error": "ToxicityMetric/BiasMetric not available in this DeepEval version.",
                "metrics": {},
            }

        test_case = LLMTestCase(input=raw_input, actual_output=raw_input)
        metrics_out: dict[str, dict] = {}

        for metric in [
            ToxicityMetric(threshold=0.5, model=self.model, include_reason=True),
            BiasMetric(threshold=0.5, model=self.model, include_reason=True),
        ]:
            metric_name = metric.__class__.__name__
            try:
                import asyncio
                asyncio.run(metric.a_measure(test_case))
                metrics_out[metric_name] = {
                    "score": round(float(metric.score), 4) if metric.score is not None else None,
                    "passed": metric.is_successful(),
                    "reason": getattr(metric, "reason", None),
                }
            except Exception as exc:
                logger.error(f"[DeepEvalSuite] {metric_name} failed: {exc}")
                metrics_out[metric_name] = {"score": None, "passed": False, "reason": str(exc)}

        n_passed = sum(1 for v in metrics_out.values() if v.get("passed"))
        return {
            "suite": "deepeval_guardrail",
            "passed": n_passed,
            "total": len(metrics_out),
            "metrics": metrics_out,
        }
