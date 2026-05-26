"""
Output guardrails: validate agent-produced data before it flows into the next phase.
These complement the input guardrails in guardrails.py by checking what the LLM returned,
not what the user sent in.
"""

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class OutputGuardrailResult:
    passed: bool
    reason: str = ""
    severity: str = "pass"   # "pass" | "warn" | "block"
    details: dict = field(default_factory=dict)


class AgentOutputGuardrails:
    """
    Post-generation validators for each research/planning agent.
    Called by the orchestrator after an agent node returns to catch bad outputs early
    before downstream agents build on corrupt data.
    """

    # ── Transport ──────────────────────────────────────────────────────────────

    def validate_transport_output(self, transport_data: dict, budget_usd: float) -> OutputGuardrailResult:
        """Ensure transport data has options and a sane cost estimate."""
        if not transport_data:
            return OutputGuardrailResult(False, "Transport agent returned empty data.", "block")

        issues: list[str] = []
        warnings: list[str] = []

        if not transport_data.get("outbound_options") and not transport_data.get("notes"):
            issues.append("No outbound transport options or notes returned.")

        cost = transport_data.get("estimated_cost_usd")
        if cost is None:
            warnings.append("Transport cost estimate is missing — budget agent may be inaccurate.")
        elif cost < 0:
            issues.append(f"Transport cost is negative: ${cost}")
        elif budget_usd > 0 and cost > budget_usd:
            warnings.append(
                f"Transport cost ${cost:.0f} exceeds total budget ${budget_usd:.0f}."
            )

        if transport_data.get("availability") is False:
            warnings.append("Transport agent reported no availability — fallback estimates are in use.")

        if issues:
            return OutputGuardrailResult(False, "; ".join(issues), "block", {"issues": issues})
        if warnings:
            return OutputGuardrailResult(True, "; ".join(warnings), "warn", {"warnings": warnings})
        return OutputGuardrailResult(True)

    # ── Hotel ─────────────────────────────────────────────────────────────────

    def validate_hotel_output(self, hotel_data: dict, budget_usd: float) -> OutputGuardrailResult:
        """Ensure hotel data is populated and within budget bounds."""
        if not hotel_data:
            return OutputGuardrailResult(False, "Hotel agent returned empty data.", "block")

        issues: list[str] = []
        warnings: list[str] = []

        if not hotel_data.get("options") and not hotel_data.get("notes"):
            issues.append("No hotel options or notes returned.")

        cost = hotel_data.get("estimated_cost_usd")
        if cost is None:
            warnings.append("Hotel cost estimate is missing.")
        elif cost < 0:
            issues.append(f"Hotel cost is negative: ${cost}")
        elif budget_usd > 0 and cost > budget_usd * 0.80:
            warnings.append(
                f"Hotel cost ${cost:.0f} is more than 80% of total budget ${budget_usd:.0f}."
            )

        stars = hotel_data.get("stars")
        if stars is not None and not (1 <= int(stars) <= 6):
            warnings.append(f"Hotel star rating {stars} is outside 1-6 range.")

        if issues:
            return OutputGuardrailResult(False, "; ".join(issues), "block", {"issues": issues})
        if warnings:
            return OutputGuardrailResult(True, "; ".join(warnings), "warn", {"warnings": warnings})
        return OutputGuardrailResult(True)

    # ── Places ────────────────────────────────────────────────────────────────

    def validate_places_output(self, places_data: dict, trip_days: int) -> OutputGuardrailResult:
        """Ensure enough places are returned for the trip duration."""
        if not places_data:
            return OutputGuardrailResult(False, "Places agent returned empty data.", "block")

        warnings: list[str] = []

        attractions = places_data.get("attractions", [])
        restaurants = places_data.get("restaurants", [])

        if len(attractions) < max(1, trip_days):
            warnings.append(
                f"Only {len(attractions)} attractions for a {trip_days}-day trip — itinerary may feel thin."
            )

        if len(restaurants) < 2:
            warnings.append("Fewer than 2 restaurant suggestions — consider adding dining recommendations.")

        if not places_data.get("local_experiences") and not places_data.get("indoor_options"):
            warnings.append("No local experiences or indoor alternatives found.")

        if warnings:
            return OutputGuardrailResult(True, "; ".join(warnings), "warn", {"warnings": warnings})
        return OutputGuardrailResult(True)

    # ── Weather ───────────────────────────────────────────────────────────────

    def validate_weather_output(self, weather_data: dict) -> OutputGuardrailResult:
        """Check weather data is present; flag severe weather for itinerary impact."""
        if not weather_data:
            return OutputGuardrailResult(True, "Weather data missing — using fallback estimates.", "warn")

        warnings: list[str] = []

        if not weather_data.get("summary"):
            warnings.append("Weather summary is empty.")

        if weather_data.get("severe_weather"):
            warnings.append(
                "Severe weather detected — itinerary should prioritise indoor options."
            )

        rain_days = weather_data.get("rain_days", 0)
        forecast = weather_data.get("daily_forecast", [])
        if forecast and rain_days > len(forecast) * 0.5:
            warnings.append(
                f"Rain expected on {rain_days}/{len(forecast)} days — consider indoor backup activities."
            )

        if warnings:
            return OutputGuardrailResult(True, "; ".join(warnings), "warn", {"warnings": warnings})
        return OutputGuardrailResult(True)

    # ── Itinerary ─────────────────────────────────────────────────────────────

    def validate_itinerary_output(self, itinerary: dict, prefs: dict) -> OutputGuardrailResult:
        """Deep-validate the LLM-generated itinerary for structure and coherence."""
        from datetime import date

        if not itinerary or not itinerary.get("days"):
            return OutputGuardrailResult(False, "Itinerary is empty.", "block")

        issues: list[str] = []
        warnings: list[str] = []

        days = itinerary["days"]
        try:
            start = date.fromisoformat(str(prefs["start_date"]))
            end = date.fromisoformat(str(prefs["end_date"]))
            expected = (end - start).days + 1

            if len(days) < expected - 1:
                warnings.append(
                    f"Itinerary has {len(days)} days but trip is {expected} days."
                )

            seen_dates: set[str] = set()
            for i, day in enumerate(days):
                day_num = day.get("day", i + 1)

                if not (day.get("morning") or day.get("afternoon") or day.get("evening")):
                    warnings.append(f"Day {day_num} has no activities.")

                day_date = day.get("date")
                if day_date:
                    if day_date in seen_dates:
                        issues.append(f"Duplicate date {day_date} in itinerary.")
                    seen_dates.add(day_date)
                    try:
                        d = date.fromisoformat(str(day_date))
                        if not (start <= d <= end):
                            warnings.append(f"Day {day_num} date {d} is outside trip range.")
                    except ValueError:
                        warnings.append(f"Day {day_num} has invalid date format: {day_date}")

                for slot in ("morning", "afternoon", "evening"):
                    activities = day.get(slot, [])
                    if isinstance(activities, list):
                        for act in activities:
                            if isinstance(act, str) and len(act.strip()) < 3:
                                warnings.append(
                                    f"Day {day_num} {slot} has a suspiciously short activity: '{act}'"
                                )

        except (KeyError, ValueError) as exc:
            warnings.append(f"Could not fully validate itinerary dates: {exc}")

        if issues:
            return OutputGuardrailResult(False, "; ".join(issues), "block", {"issues": issues})
        if warnings:
            return OutputGuardrailResult(True, "; ".join(warnings), "warn", {"warnings": warnings})
        return OutputGuardrailResult(True)

    # ── Budget ────────────────────────────────────────────────────────────────

    def validate_budget_output(self, budget_summary: dict, budget_usd: float) -> OutputGuardrailResult:
        """Validate budget arithmetic and flag constraint violations."""
        if not budget_summary:
            return OutputGuardrailResult(False, "Budget agent returned empty data.", "block")

        issues: list[str] = []
        warnings: list[str] = []

        fields = ["transport_cost", "hotel_cost", "activities_cost", "food_cost", "misc_cost"]
        for f in fields:
            val = budget_summary.get(f)
            if val is None:
                warnings.append(f"Missing budget field: {f}")
            elif float(val) < 0:
                issues.append(f"Negative cost in {f}: ${val}")

        total_spent = float(budget_summary.get("total_spent", 0))
        component_sum = sum(float(budget_summary.get(f, 0)) for f in fields)
        if component_sum > 0 and total_spent > 0:
            diff_pct = abs(component_sum - total_spent) / max(component_sum, total_spent)
            if diff_pct > 0.05:
                issues.append(
                    f"Budget mismatch: components sum to ${component_sum:.0f} "
                    f"but total_spent is ${total_spent:.0f} (diff {diff_pct:.1%})"
                )

        if budget_usd > 0 and total_spent > budget_usd * 1.10:
            warnings.append(
                f"Plan exceeds budget by {(total_spent / budget_usd - 1):.1%} "
                f"(${total_spent:.0f} vs ${budget_usd:.0f} budget)."
            )

        if issues:
            return OutputGuardrailResult(False, "; ".join(issues), "block", {"issues": issues})
        if warnings:
            return OutputGuardrailResult(True, "; ".join(warnings), "warn", {"warnings": warnings})
        return OutputGuardrailResult(True)

    # ── Convenience: run all post-pipeline checks ─────────────────────────────

    def run_full_output_check(self, state: dict) -> dict[str, OutputGuardrailResult]:
        """
        Run all output guardrails for a completed pipeline state.
        Returns a dict of {check_name: OutputGuardrailResult}.
        """
        prefs = state.get("trip_preferences", {})
        budget_usd = float(prefs.get("budget_usd", 0))

        try:
            from datetime import date
            start = date.fromisoformat(str(prefs.get("start_date", "2000-01-01")))
            end = date.fromisoformat(str(prefs.get("end_date", "2000-01-01")))
            trip_days = max((end - start).days, 1)
        except (ValueError, TypeError):
            trip_days = 1

        results: dict[str, OutputGuardrailResult] = {}

        results["transport"] = self.validate_transport_output(
            state.get("transport_data", {}), budget_usd
        )
        results["hotel"] = self.validate_hotel_output(
            state.get("hotel_data", {}), budget_usd
        )
        results["places"] = self.validate_places_output(
            state.get("places_data", {}), trip_days
        )
        results["weather"] = self.validate_weather_output(
            state.get("weather_data", {})
        )
        results["itinerary"] = self.validate_itinerary_output(
            state.get("itinerary", {}), prefs
        )
        results["budget"] = self.validate_budget_output(
            state.get("budget_summary", {}), budget_usd
        )

        return results


# Module-level singleton
agent_output_guardrails = AgentOutputGuardrails()
