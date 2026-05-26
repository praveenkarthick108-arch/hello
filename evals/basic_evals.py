"""
Basic evaluators for the trip planner — deterministic, zero external dependencies.

Each evaluator returns an EvalResult with a 0–1 score and a pass/fail flag.
BasicEvalSuite runs all evaluators and returns an aggregated summary dict.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

logger = logging.getLogger(__name__)


# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class EvalResult:
    name: str
    score: float        # 0.0 – 1.0
    passed: bool
    reason: str = ""
    details: dict = field(default_factory=dict)


# ── Individual evaluators ─────────────────────────────────────────────────────

class ItineraryCompletenessEval:
    """
    Checks that the itinerary covers the full trip duration and that each day
    has activities in at least two of the three time slots.
    """
    name = "itinerary_completeness"
    threshold = 0.8

    def evaluate(self, state: dict) -> EvalResult:
        itinerary = state.get("itinerary", {})
        prefs = state.get("trip_preferences", {})
        days = itinerary.get("days", [])

        if not days:
            return EvalResult(self.name, 0.0, False, "No days in itinerary.")

        try:
            start = date.fromisoformat(str(prefs["start_date"]))
            end = date.fromisoformat(str(prefs["end_date"]))
            expected_days = (end - start).days + 1
        except (KeyError, ValueError):
            expected_days = len(days)

        coverage = min(1.0, len(days) / max(expected_days, 1))

        slot_scores = []
        for day in days:
            filled = sum(
                bool(day.get(slot))
                for slot in ("morning", "afternoon", "evening")
            )
            slot_scores.append(filled / 3.0)

        avg_slots = sum(slot_scores) / len(slot_scores)
        score = round(coverage * 0.5 + avg_slots * 0.5, 3)

        return EvalResult(
            self.name, score, score >= self.threshold,
            f"{len(days)}/{expected_days} days covered, avg slot fill {avg_slots:.1%}",
            {"days_covered": len(days), "expected_days": expected_days, "avg_slot_fill": avg_slots},
        )


class BudgetAccuracyEval:
    """
    Verifies that budget component costs sum to total_spent (within 5%)
    and that the plan does not exceed the stated budget by more than 10%.
    """
    name = "budget_accuracy"
    threshold = 0.9

    def evaluate(self, state: dict) -> EvalResult:
        budget_summary = state.get("budget_summary", {})
        prefs = state.get("trip_preferences", {})

        if not budget_summary:
            return EvalResult(self.name, 0.0, False, "No budget summary in state.")

        issues: list[str] = []
        total_budget = float(prefs.get("budget_usd", 0))
        components = {
            k: float(budget_summary.get(k, 0))
            for k in ("transport_cost", "hotel_cost", "activities_cost", "food_cost", "misc_cost")
        }
        total_spent = float(budget_summary.get("total_spent", 0))
        component_sum = sum(components.values())

        for name, val in components.items():
            if val < 0:
                issues.append(f"Negative {name}: ${val}")

        if component_sum > 0 and total_spent > 0:
            diff_ratio = abs(component_sum - total_spent) / max(component_sum, total_spent)
            if diff_ratio > 0.05:
                issues.append(
                    f"Sum mismatch: components=${component_sum:.0f}, total_spent=${total_spent:.0f}"
                )

        if total_budget > 0 and total_spent > total_budget * 1.10:
            issues.append(
                f"Over budget by {(total_spent / total_budget - 1):.1%} "
                f"(${total_spent:.0f} vs ${total_budget:.0f})"
            )

        score = round(max(0.0, 1.0 - len(issues) * 0.25), 3)

        return EvalResult(
            self.name, score, score >= self.threshold,
            "; ".join(issues) if issues else "Budget arithmetic is consistent.",
            {"total_budget": total_budget, "total_spent": total_spent, "issues": issues},
        )


class DateConsistencyEval:
    """
    Validates that start_date < end_date, dates are not in the past,
    and all itinerary day dates fall within the trip range.
    """
    name = "date_consistency"
    threshold = 1.0

    def evaluate(self, state: dict) -> EvalResult:
        prefs = state.get("trip_preferences", {})
        itinerary = state.get("itinerary", {})
        issues: list[str] = []

        try:
            start = date.fromisoformat(str(prefs["start_date"]))
            end = date.fromisoformat(str(prefs["end_date"]))

            if end <= start:
                issues.append("end_date is not after start_date.")
            if start < date.today():
                issues.append(f"start_date {start} is in the past.")

            for day_obj in itinerary.get("days", []):
                raw = day_obj.get("date")
                if raw:
                    try:
                        d = date.fromisoformat(str(raw))
                        if not (start <= d <= end):
                            issues.append(f"Day date {d} is outside trip range {start}–{end}.")
                    except ValueError:
                        issues.append(f"Unparseable day date: {raw}")
        except (KeyError, ValueError) as exc:
            issues.append(f"Date parsing error: {exc}")

        score = round(max(0.0, 1.0 - len(issues) * 0.33), 3)

        return EvalResult(
            self.name, score, not bool(issues),
            "; ".join(issues) if issues else "All dates are consistent.",
            {"issues": issues},
        )


class ContentQualityEval:
    """
    Measures content richness: activity density per day, hotel coverage,
    meal coverage, and presence of transport / hotel research data.
    """
    name = "content_quality"
    threshold = 0.7

    def evaluate(self, state: dict) -> EvalResult:
        scores: dict[str, float] = {}

        itinerary = state.get("itinerary", {})
        days = itinerary.get("days", [])
        if days:
            all_activities = []
            for day in days:
                for slot in ("morning", "afternoon", "evening"):
                    all_activities.extend(day.get(slot, []))

            scores["activity_density"] = min(1.0, (len(all_activities) / len(days)) / 6.0)
            scores["hotel_coverage"] = sum(1 for d in days if d.get("hotel")) / len(days)
            avg_meals = sum(len(d.get("meals", [])) for d in days) / len(days)
            scores["meal_coverage"] = min(1.0, avg_meals / 2.0)

        hotel_data = state.get("hotel_data", {})
        if hotel_data:
            scores["hotel_data_richness"] = (
                bool(hotel_data.get("options")) * 0.5
                + bool(hotel_data.get("estimated_cost_usd")) * 0.5
            )

        transport_data = state.get("transport_data", {})
        if transport_data:
            scores["transport_data_richness"] = (
                bool(transport_data.get("outbound_options")) * 0.5
                + bool(transport_data.get("estimated_cost_usd")) * 0.5
            )

        places_data = state.get("places_data", {})
        if places_data:
            has_attractions = bool(places_data.get("attractions"))
            has_restaurants = bool(places_data.get("restaurants"))
            scores["places_richness"] = (has_attractions + has_restaurants) / 2.0

        if not scores:
            return EvalResult(self.name, 0.0, False, "No data to evaluate.")

        avg_score = round(sum(scores.values()) / len(scores), 3)

        return EvalResult(
            self.name, avg_score, avg_score >= self.threshold,
            f"Content quality across {len(scores)} dimensions: avg {avg_score:.2f}",
            scores,
        )


class GuardrailComplianceEval:
    """Reports the guardrail check result as a scored metric."""
    name = "guardrail_compliance"
    threshold = 1.0

    _severity_score = {"pass": 1.0, "warn": 0.7, "block": 0.0}

    def evaluate(self, state: dict) -> EvalResult:
        gr = state.get("guardrail_result", {})
        if not gr:
            return EvalResult(self.name, 0.0, False, "No guardrail result in state.")

        severity = gr.get("severity", "block")
        passed = gr.get("passed", False)
        score = round(self._severity_score.get(severity, 0.0), 3)

        return EvalResult(
            self.name, score, passed,
            f"Severity: {severity}. {gr.get('reason', '')}",
            {
                "severity": severity,
                "pii_detected": gr.get("pii_detected", []),
                "details": gr.get("details", {}),
            },
        )


class ReviewApprovalEval:
    """Scores the final review agent decision."""
    name = "review_approval"
    threshold = 1.0

    def evaluate(self, state: dict) -> EvalResult:
        review = state.get("review_status", {})
        if not review:
            return EvalResult(self.name, 0.0, False, "No review status in state.")

        approved = review.get("approved", False)
        conflicts = review.get("conflicts", [])
        warnings = review.get("warnings", [])

        if approved and not conflicts:
            score = 1.0
        elif approved:
            score = 0.7
        else:
            score = 0.0

        label = "Approved" if approved else "Not approved"
        return EvalResult(
            self.name, score, approved,
            f"{label}. Conflicts: {len(conflicts)}, Warnings: {len(warnings)}",
            {"conflicts": conflicts, "warnings": warnings},
        )


class OutputGuardrailSummaryEval:
    """
    Runs the output guardrails from src/output_guardrails.py and converts the
    results into a single scored metric.
    """
    name = "output_guardrails"
    threshold = 0.8

    def evaluate(self, state: dict) -> EvalResult:
        try:
            from src.output_guardrails import agent_output_guardrails
        except ImportError:
            return EvalResult(self.name, 0.0, False, "Could not import output_guardrails.")

        results = agent_output_guardrails.run_full_output_check(state)

        severity_score = {"pass": 1.0, "warn": 0.7, "block": 0.0}
        scores_per_check = {
            name: severity_score.get(r.severity, 0.0)
            for name, r in results.items()
        }
        avg = round(sum(scores_per_check.values()) / len(scores_per_check), 3) if scores_per_check else 0.0

        blocked = [n for n, r in results.items() if r.severity == "block"]
        warned = [n for n, r in results.items() if r.severity == "warn"]

        reason = (
            f"Blocked: {blocked}. " if blocked else ""
        ) + (f"Warned: {warned}." if warned else "All checks passed.")

        return EvalResult(
            self.name, avg, avg >= self.threshold,
            reason,
            {"check_scores": scores_per_check, "blocked": blocked, "warned": warned},
        )


# ── Suite ─────────────────────────────────────────────────────────────────────

class BasicEvalSuite:
    """Run all basic evaluators and return an aggregated summary."""

    def __init__(self, include_output_guardrails: bool = True):
        self.evaluators: list = [
            ItineraryCompletenessEval(),
            BudgetAccuracyEval(),
            DateConsistencyEval(),
            ContentQualityEval(),
            GuardrailComplianceEval(),
            ReviewApprovalEval(),
        ]
        if include_output_guardrails:
            self.evaluators.append(OutputGuardrailSummaryEval())

    def run(self, state: dict) -> dict:
        results: list[EvalResult] = []
        for ev in self.evaluators:
            try:
                results.append(ev.evaluate(state))
            except Exception as exc:
                logger.error(f"[BasicEvalSuite] {ev.name} crashed: {exc}")
                results.append(EvalResult(ev.name, 0.0, False, f"Eval error: {exc}"))

        n_passed = sum(1 for r in results if r.passed)
        avg_score = round(sum(r.score for r in results) / len(results), 3) if results else 0.0

        return {
            "suite": "basic_evals",
            "passed": n_passed,
            "total": len(results),
            "pass_rate": round(n_passed / len(results), 3) if results else 0.0,
            "avg_score": avg_score,
            "results": results,
        }
