"""
RAGAS-based evaluation for the trip planner.

The itinerary is treated as the "answer" generated from retrieved contexts
(weather, hotel search, transport search, places search).

Metrics used:
  - Faithfulness        : Is the itinerary grounded in the retrieved context?
  - AnswerRelevancy     : Is the itinerary relevant to the user's request?

RAGAS is optional — if not installed the evaluator returns a graceful error dict.
Install with:  pip install ragas
"""

from __future__ import annotations

import logging
import math
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from ragas import evaluate as _ragas_evaluate
    from ragas.metrics import Faithfulness, AnswerRelevancy
    from ragas.dataset_schema import SingleTurnSample, EvaluationDataset
    RAGAS_AVAILABLE = True
except ImportError:
    RAGAS_AVAILABLE = False
    logger.warning("ragas not installed — RAGASEvaluator will return error dicts. pip install ragas")


# ── State → text helpers ──────────────────────────────────────────────────────

def _itinerary_to_text(state: dict) -> str:
    """Flatten itinerary + budget into a readable paragraph for RAGAS."""
    prefs = state.get("trip_preferences", {})
    budget = state.get("budget_summary", {})
    itinerary = state.get("itinerary", {})

    dest = prefs.get("destination", "the destination")
    origin = prefs.get("origin", "the origin")
    start = prefs.get("start_date", "")
    end = prefs.get("end_date", "")
    travelers = prefs.get("travelers", 1)
    budget_usd = prefs.get("budget_usd", 0)

    lines = [
        f"Trip from {origin} to {dest} ({start} to {end}) "
        f"for {travelers} traveler(s) with ${budget_usd} budget."
    ]

    if budget:
        lines.append(
            f"Budget breakdown — Transport: ${budget.get('transport_cost', 0):.0f}, "
            f"Hotel: ${budget.get('hotel_cost', 0):.0f}, "
            f"Activities: ${budget.get('activities_cost', 0):.0f}, "
            f"Food: ${budget.get('food_cost', 0):.0f}. "
            f"Total spend: ${budget.get('total_spent', 0):.0f}."
        )

    for day_obj in itinerary.get("days", []):
        lines.append(f"\nDay {day_obj.get('day', '?')} ({day_obj.get('date', '')}):")
        for slot in ("morning", "afternoon", "evening"):
            acts = day_obj.get(slot, [])
            if acts:
                lines.append(f"  {slot.capitalize()}: {', '.join(str(a) for a in acts)}")
        if day_obj.get("hotel"):
            lines.append(f"  Hotel: {day_obj['hotel']}")
        meals = day_obj.get("meals", [])
        if meals:
            lines.append(f"  Meals: {', '.join(str(m) for m in meals)}")
        if day_obj.get("transport_notes"):
            lines.append(f"  Transport: {day_obj['transport_notes']}")

    return "\n".join(lines)


def _build_contexts(state: dict) -> list[str]:
    """Build retrieval context list from all research agent outputs."""
    contexts: list[str] = []

    weather = state.get("weather_data", {})
    if weather.get("summary"):
        contexts.append(f"Weather forecast: {weather['summary']}")

    hotel = state.get("hotel_data", {})
    if hotel.get("notes"):
        contexts.append(f"Hotel research: {hotel['notes']}")
    if hotel.get("options"):
        opts = [str(o) for o in hotel["options"][:4]]
        contexts.append(f"Hotel options: {'; '.join(opts)}")

    transport = state.get("transport_data", {})
    if transport.get("notes"):
        contexts.append(f"Transport research: {transport['notes']}")
    if transport.get("outbound_options"):
        opts = [str(o) for o in transport["outbound_options"][:4]]
        contexts.append(f"Transport options: {'; '.join(opts)}")

    places = state.get("places_data", {})
    attractions = [str(a) for a in places.get("attractions", [])[:6]]
    if attractions:
        contexts.append(f"Attractions: {', '.join(attractions)}")
    restaurants = [str(r) for r in places.get("restaurants", [])[:6]]
    if restaurants:
        contexts.append(f"Restaurants: {', '.join(restaurants)}")
    experiences = [str(e) for e in places.get("local_experiences", [])[:4]]
    if experiences:
        contexts.append(f"Local experiences: {', '.join(experiences)}")

    profile = state.get("user_profile", {})
    if not profile.get("new_user") and profile.get("inferred_preferences"):
        contexts.append(f"User preferences from past trips: {profile['inferred_preferences']}")

    return contexts or ["No retrieved context available."]


# ── Evaluator ─────────────────────────────────────────────────────────────────

class RAGASEvaluator:
    """
    Wraps RAGAS evaluate() for a single or batch of trip states.
    Gracefully degrades if ragas is not installed.
    """

    def __init__(self, llm=None, embeddings=None):
        self.available = RAGAS_AVAILABLE
        self._llm = llm
        self._embeddings = embeddings

    def build_sample(self, state: dict) -> dict:
        """Return raw fields that will be passed to SingleTurnSample."""
        return {
            "user_input": state.get("raw_input", ""),
            "response": _itinerary_to_text(state),
            "retrieved_contexts": _build_contexts(state),
        }

    def evaluate(self, state: dict) -> dict:
        """Run RAGAS on a single completed trip state."""
        if not self.available:
            return {
                "suite": "ragas",
                "error": "ragas not installed. Run: pip install ragas",
                "metrics": {},
            }

        try:
            sample_data = self.build_sample(state)
            if not sample_data["user_input"] or not sample_data["response"]:
                return {"suite": "ragas", "error": "Insufficient state data.", "metrics": {}}

            sample = SingleTurnSample(
                user_input=sample_data["user_input"],
                response=sample_data["response"],
                retrieved_contexts=sample_data["retrieved_contexts"],
            )
            dataset = EvaluationDataset(samples=[sample])

            metrics = [Faithfulness(), AnswerRelevancy()]
            kwargs: dict = {}
            if self._llm:
                kwargs["llm"] = self._llm
            if self._embeddings:
                kwargs["embeddings"] = self._embeddings

            result = _ragas_evaluate(dataset=dataset, metrics=metrics, **kwargs)
            df = result.to_pandas()

            metrics_out: dict[str, float] = {}
            for col in df.columns:
                val = df[col].iloc[0]
                if isinstance(val, (int, float)) and not math.isnan(float(val)):
                    metrics_out[col] = round(float(val), 4)

            avg_score = (
                round(sum(metrics_out.values()) / len(metrics_out), 4)
                if metrics_out else 0.0
            )

            return {
                "suite": "ragas",
                "metrics": metrics_out,
                "avg_score": avg_score,
            }

        except Exception as exc:
            logger.error(f"[RAGASEvaluator] Evaluation failed: {exc}")
            return {"suite": "ragas", "error": str(exc), "metrics": {}}

    def evaluate_batch(self, states: list[dict]) -> dict:
        """Evaluate multiple trip states in a single RAGAS call."""
        if not self.available:
            return {"suite": "ragas", "error": "ragas not installed.", "metrics": {}}

        try:
            samples = []
            for state in states:
                s = self.build_sample(state)
                if s["user_input"] and s["response"]:
                    samples.append(SingleTurnSample(
                        user_input=s["user_input"],
                        response=s["response"],
                        retrieved_contexts=s["retrieved_contexts"],
                    ))

            if not samples:
                return {"suite": "ragas", "error": "No valid samples.", "metrics": {}}

            dataset = EvaluationDataset(samples=samples)
            metrics = [Faithfulness(), AnswerRelevancy()]
            kwargs: dict = {}
            if self._llm:
                kwargs["llm"] = self._llm
            if self._embeddings:
                kwargs["embeddings"] = self._embeddings

            result = _ragas_evaluate(dataset=dataset, metrics=metrics, **kwargs)
            df = result.to_pandas()

            metrics_out: dict[str, float] = {}
            for col in df.select_dtypes("number").columns:
                metrics_out[col] = round(float(df[col].mean()), 4)

            avg_score = (
                round(sum(metrics_out.values()) / len(metrics_out), 4)
                if metrics_out else 0.0
            )

            return {
                "suite": "ragas",
                "n_samples": len(samples),
                "metrics": metrics_out,
                "avg_score": avg_score,
            }

        except Exception as exc:
            logger.error(f"[RAGASEvaluator] Batch evaluation failed: {exc}")
            return {"suite": "ragas", "error": str(exc), "metrics": {}}
