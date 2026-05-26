"""
Tests for evals/basic_evals.py — all deterministic, no LLM calls, no API keys.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from evals.basic_evals import (
    BasicEvalSuite,
    BudgetAccuracyEval,
    ContentQualityEval,
    DateConsistencyEval,
    GuardrailComplianceEval,
    ItineraryCompletenessEval,
    ReviewApprovalEval,
)


def _future(days: int = 30) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


# ── ItineraryCompletenessEval ─────────────────────────────────────────────────

class TestItineraryCompletenessEval:
    ev = ItineraryCompletenessEval()

    def test_full_coverage_passes(self, sample_state):
        r = self.ev.evaluate(sample_state)
        assert r.passed
        assert r.score >= 0.8

    def test_no_days_fails(self, empty_itinerary_state):
        r = self.ev.evaluate(empty_itinerary_state)
        assert not r.passed
        assert r.score == 0.0

    def test_empty_slots_lowers_score(self, sample_state):
        state = dict(sample_state)
        state["itinerary"] = {
            "days": [
                {"day": i, "date": _future(i), "morning": [], "afternoon": [], "evening": []}
                for i in range(1, 6)
            ]
        }
        r = self.ev.evaluate(state)
        assert r.score < 0.8

    def test_fewer_days_than_expected_lowers_score(self, sample_state):
        state = dict(sample_state)
        prefs = state["trip_preferences"]
        state["itinerary"] = {
            "days": [
                {
                    "day": i,
                    "date": _future(i),
                    "morning": ["Act"],
                    "afternoon": ["Act"],
                    "evening": ["Act"],
                }
                for i in range(1, 3)   # only 2 of 5 days
            ]
        }
        r = self.ev.evaluate(state)
        assert r.score < 0.8

    def test_result_name_is_correct(self, sample_state):
        r = self.ev.evaluate(sample_state)
        assert r.name == "itinerary_completeness"

    def test_details_contain_expected_keys(self, sample_state):
        r = self.ev.evaluate(sample_state)
        assert "days_covered" in r.details
        assert "expected_days" in r.details


# ── BudgetAccuracyEval ────────────────────────────────────────────────────────

class TestBudgetAccuracyEval:
    ev = BudgetAccuracyEval()

    def test_correct_budget_passes(self, sample_state):
        r = self.ev.evaluate(sample_state)
        assert r.passed
        assert r.score >= 0.9

    def test_missing_budget_summary_fails(self, sample_state):
        state = dict(sample_state)
        state["budget_summary"] = {}
        r = self.ev.evaluate(state)
        assert not r.passed
        assert r.score == 0.0

    def test_sum_mismatch_lowers_score(self, sample_state):
        state = dict(sample_state)
        state["budget_summary"] = {
            **sample_state["budget_summary"],
            "total_spent": 9999,   # components sum to 3500, not 9999
        }
        r = self.ev.evaluate(state)
        assert r.score < 0.9

    def test_over_budget_lowers_score(self, over_budget_state):
        r = self.ev.evaluate(over_budget_state)
        assert r.score < 0.9

    def test_negative_cost_lowers_score(self, sample_state):
        state = dict(sample_state)
        state["budget_summary"] = {**sample_state["budget_summary"], "transport_cost": -100}
        r = self.ev.evaluate(state)
        assert r.score < 1.0

    def test_details_contain_total_budget(self, sample_state):
        r = self.ev.evaluate(sample_state)
        assert "total_budget" in r.details
        assert r.details["total_budget"] == 5000


# ── DateConsistencyEval ───────────────────────────────────────────────────────

class TestDateConsistencyEval:
    ev = DateConsistencyEval()

    def test_consistent_dates_passes(self, sample_state):
        r = self.ev.evaluate(sample_state)
        assert r.passed
        assert r.score == 1.0

    def test_past_start_date_fails(self, sample_state):
        state = dict(sample_state)
        state["trip_preferences"] = {
            **sample_state["trip_preferences"],
            "start_date": "2020-01-01",
            "end_date": "2020-01-05",
        }
        state["itinerary"] = {"days": []}
        r = self.ev.evaluate(state)
        assert not r.passed

    def test_end_before_start_fails(self, sample_state):
        start = _future(20)
        end = _future(10)
        state = dict(sample_state)
        state["trip_preferences"] = {
            **sample_state["trip_preferences"],
            "start_date": start,
            "end_date": end,
        }
        state["itinerary"] = {"days": []}
        r = self.ev.evaluate(state)
        assert not r.passed

    def test_day_outside_trip_range_fails(self, sample_state):
        state = dict(sample_state)
        state["itinerary"] = {
            "days": [{"day": 1, "date": "2099-12-31", "morning": [], "afternoon": [], "evening": []}]
        }
        r = self.ev.evaluate(state)
        assert r.score < 1.0

    def test_missing_dates_in_prefs_handles_gracefully(self):
        r = self.ev.evaluate({"trip_preferences": {}, "itinerary": {"days": []}})
        assert isinstance(r.passed, bool)


# ── ContentQualityEval ────────────────────────────────────────────────────────

class TestContentQualityEval:
    ev = ContentQualityEval()

    def test_rich_state_passes(self, sample_state):
        r = self.ev.evaluate(sample_state)
        assert r.passed
        assert r.score >= 0.7

    def test_empty_state_fails(self):
        r = self.ev.evaluate({})
        assert not r.passed
        assert r.score == 0.0

    def test_itinerary_without_hotels_lowers_score(self, sample_state):
        state = dict(sample_state)
        days = [dict(d, hotel=None) for d in sample_state["itinerary"]["days"]]
        state["itinerary"] = {"days": days}
        r = self.ev.evaluate(state)
        # Should still have a score but hotel_coverage dimension will be 0
        assert "hotel_coverage" in r.details

    def test_score_between_0_and_1(self, sample_state):
        r = self.ev.evaluate(sample_state)
        assert 0.0 <= r.score <= 1.0

    def test_name_correct(self, sample_state):
        r = self.ev.evaluate(sample_state)
        assert r.name == "content_quality"


# ── GuardrailComplianceEval ───────────────────────────────────────────────────

class TestGuardrailComplianceEval:
    ev = GuardrailComplianceEval()

    def test_pass_severity_scores_1(self, sample_state):
        r = self.ev.evaluate(sample_state)
        assert r.passed
        assert r.score == 1.0

    def test_warn_severity_scores_07(self, sample_state):
        state = dict(sample_state)
        state["guardrail_result"] = {
            "passed": True,
            "reason": "Not clearly travel-related.",
            "severity": "warn",
            "pii_detected": [],
        }
        r = self.ev.evaluate(state)
        assert r.passed
        assert r.score == pytest.approx(0.7)

    def test_block_severity_fails(self, blocked_guardrail_state):
        r = self.ev.evaluate(blocked_guardrail_state)
        assert not r.passed
        assert r.score == 0.0

    def test_missing_guardrail_result_fails(self, sample_state):
        state = dict(sample_state)
        state["guardrail_result"] = {}
        r = self.ev.evaluate(state)
        assert not r.passed


# ── ReviewApprovalEval ────────────────────────────────────────────────────────

class TestReviewApprovalEval:
    ev = ReviewApprovalEval()

    def test_approved_no_conflicts_scores_1(self, sample_state):
        r = self.ev.evaluate(sample_state)
        assert r.passed
        assert r.score == 1.0

    def test_approved_with_conflicts_scores_07(self, sample_state):
        state = dict(sample_state)
        state["review_status"] = {
            "approved": True,
            "conflicts": ["Hotel exceeds budget."],
            "warnings": [],
            "retry_reasons": [],
        }
        r = self.ev.evaluate(state)
        assert r.passed
        assert r.score == pytest.approx(0.7)

    def test_not_approved_fails(self, sample_state):
        state = dict(sample_state)
        state["review_status"] = {
            "approved": False,
            "conflicts": ["Transport unavailable."],
            "warnings": [],
            "retry_reasons": ["Retry transport agent."],
        }
        r = self.ev.evaluate(state)
        assert not r.passed
        assert r.score == 0.0

    def test_missing_review_status_fails(self, sample_state):
        state = dict(sample_state)
        state["review_status"] = {}
        r = self.ev.evaluate(state)
        assert not r.passed


# ── BasicEvalSuite ────────────────────────────────────────────────────────────

class TestBasicEvalSuite:
    def test_full_run_on_good_state(self, sample_state):
        suite = BasicEvalSuite(include_output_guardrails=False)
        result = suite.run(sample_state)

        assert result["suite"] == "basic_evals"
        assert result["total"] == 6
        assert isinstance(result["avg_score"], float)
        assert 0.0 <= result["avg_score"] <= 1.0
        assert isinstance(result["results"], list)
        assert len(result["results"]) == 6

    def test_pass_rate_is_float_between_0_and_1(self, sample_state):
        suite = BasicEvalSuite(include_output_guardrails=False)
        result = suite.run(sample_state)
        assert 0.0 <= result["pass_rate"] <= 1.0

    def test_good_state_high_pass_rate(self, sample_state):
        suite = BasicEvalSuite(include_output_guardrails=False)
        result = suite.run(sample_state)
        assert result["pass_rate"] >= 0.8, f"Expected high pass rate, got {result['pass_rate']}"

    def test_bad_state_low_pass_rate(self, blocked_guardrail_state, empty_itinerary_state):
        state = dict(empty_itinerary_state)
        state["guardrail_result"] = blocked_guardrail_state["guardrail_result"]
        state["review_status"] = {"approved": False, "conflicts": ["Bad input"], "warnings": []}
        suite = BasicEvalSuite(include_output_guardrails=False)
        result = suite.run(state)
        assert result["pass_rate"] < 0.8

    def test_each_result_has_required_fields(self, sample_state):
        suite = BasicEvalSuite(include_output_guardrails=False)
        result = suite.run(sample_state)
        for r in result["results"]:
            assert hasattr(r, "name")
            assert hasattr(r, "score")
            assert hasattr(r, "passed")
            assert hasattr(r, "reason")
            assert 0.0 <= r.score <= 1.0

    def test_suite_handles_eval_crash_gracefully(self, sample_state):
        """If one evaluator raises, suite should still return results for others."""
        suite = BasicEvalSuite(include_output_guardrails=False)
        # Inject a broken evaluator
        class BrokenEval:
            name = "broken"
            def evaluate(self, _state):
                raise RuntimeError("simulated crash")

        suite.evaluators.insert(0, BrokenEval())
        result = suite.run(sample_state)
        names = [r.name for r in result["results"]]
        assert "broken" in names
        broken = next(r for r in result["results"] if r.name == "broken")
        assert not broken.passed
        assert "crash" in broken.reason.lower() or "error" in broken.reason.lower()
