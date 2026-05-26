"""
Shared pytest fixtures for the trip planner test suite.
All fixtures are purely in-memory — no API calls, no DB, no files.
"""

from __future__ import annotations

from datetime import date, timedelta
import pytest


def _future_start(offset_days: int = 30) -> date:
    return date.today() + timedelta(days=offset_days)


@pytest.fixture
def sample_state() -> dict:
    """
    A fully populated TripPlannerState dict representing a successful 5-day
    Paris trip for 2 travellers with a $5,000 budget.
    All dates are set in the future relative to today so date-consistency
    checks always pass.
    """
    start = _future_start(30)
    end = start + timedelta(days=4)

    return {
        "user_id": "user_test_1",
        "session_id": "session_test_abc",
        "raw_input": (
            "Plan a 5-day trip to Paris for 2 people from New York "
            "with a $5000 budget. We love museums and food tours."
        ),
        "guardrail_result": {
            "passed": True,
            "reason": "Input is safe and travel-related.",
            "severity": "pass",
            "pii_detected": [],
            "details": {
                "is_safe": True,
                "is_travel_related": True,
                "has_prompt_injection": False,
            },
        },
        "trip_preferences": {
            "destination": "Paris",
            "origin": "New York",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "budget_usd": 5000,
            "travelers": 2,
            "trip_type": "leisure",
            "dietary_restrictions": [],
            "preferred_activities": ["museums", "food tours"],
            "mobility_needs": "none",
            "budget_style": "mid",
        },
        "user_profile": {
            "new_user": True,
            "past_trips": [],
            "inferred_preferences": {},
        },
        "weather_data": {
            "daily_forecast": [
                {
                    "date": (start + timedelta(days=i)).isoformat(),
                    "temp_high": 72,
                    "temp_low": 58,
                    "condition": "sunny",
                }
                for i in range(5)
            ],
            "summary": "Warm and sunny. Average high 72°F, low 58°F.",
            "severe_weather": False,
            "rain_days": 0,
        },
        "transport_data": {
            "outbound_options": [
                {"type": "flight", "provider": "Air France", "cost": 450, "duration": "7h30m"},
                {"type": "flight", "provider": "Delta", "cost": 380, "duration": "8h"},
            ],
            "return_options": [
                {"type": "flight", "provider": "Air France", "cost": 450, "duration": "8h"}
            ],
            "estimated_cost_usd": 900,
            "availability": True,
            "notes": "Multiple direct flights from JFK to CDG daily.",
        },
        "hotel_data": {
            "options": [
                {"name": "Hotel Le Marais", "stars": 4, "price_per_night": 200},
                {"name": "Mercure Paris Centre", "stars": 3, "price_per_night": 150},
            ],
            "recommended": {"name": "Hotel Le Marais", "stars": 4, "price_per_night": 200},
            "estimated_cost_usd": 1000,
            "within_budget": True,
            "stars": 4,
            "notes": "4-star hotel in Le Marais, walking distance to Louvre.",
        },
        "places_data": {
            "attractions": [
                "Eiffel Tower", "Louvre Museum", "Notre-Dame Cathedral",
                "Musée d'Orsay", "Versailles", "Centre Pompidou",
            ],
            "restaurants": [
                "Café de Flore", "Le Jules Verne", "Breizh Café", "L'As du Fallafel",
            ],
            "local_experiences": [
                "Seine River cruise", "Montmartre walking tour", "French cooking class",
            ],
            "indoor_options": ["Louvre Museum", "Musée d'Orsay", "Centre Pompidou"],
            "outdoor_options": ["Champs-Élysées", "Luxembourg Gardens", "Tuileries Garden"],
        },
        "budget_summary": {
            "total_budget": 5000,
            "transport_cost": 900,
            "hotel_cost": 1000,
            "activities_cost": 600,
            "food_cost": 750,
            "misc_cost": 250,
            "total_spent": 3500,
            "remaining": 1500,
            "within_budget": True,
            "optimizations": [
                "Book flights in advance for better rates.",
                "Use Paris Visite card for public transport.",
            ],
        },
        "itinerary": {
            "days": [
                {
                    "day": 1,
                    "date": start.isoformat(),
                    "morning": ["Arrive at CDG, transfer to hotel", "Check in and freshen up"],
                    "afternoon": ["Visit Notre-Dame Cathedral", "Walk along Île de la Cité"],
                    "evening": ["Dinner at Café de Flore", "Evening stroll along the Seine"],
                    "hotel": "Hotel Le Marais",
                    "meals": ["Café de Flore (dinner)"],
                    "transport_notes": "RER B from CDG to Châtelet–Les Halles (35 min)",
                },
                {
                    "day": 2,
                    "date": (start + timedelta(days=1)).isoformat(),
                    "morning": ["Eiffel Tower (pre-booked tickets)", "Champ de Mars picnic"],
                    "afternoon": ["Seine River cruise", "Musée d'Orsay"],
                    "evening": ["Dinner at Le Jules Verne", "Night view of Eiffel Tower lights"],
                    "hotel": "Hotel Le Marais",
                    "meals": ["Le Jules Verne (dinner)"],
                    "transport_notes": "Metro Line 6 to Trocadéro",
                },
                {
                    "day": 3,
                    "date": (start + timedelta(days=2)).isoformat(),
                    "morning": ["Louvre Museum (full morning)", "Tuileries Garden walk"],
                    "afternoon": ["Palais Royal", "French cooking class in Le Marais"],
                    "evening": ["Dinner at Breizh Café", "Explore Le Marais neighbourhood"],
                    "hotel": "Hotel Le Marais",
                    "meals": ["Breizh Café (dinner)"],
                    "transport_notes": "20-minute walk from hotel to Louvre",
                },
                {
                    "day": 4,
                    "date": (start + timedelta(days=3)).isoformat(),
                    "morning": ["Day trip to Versailles", "Palace of Versailles tour"],
                    "afternoon": ["Versailles gardens", "Return to Paris"],
                    "evening": ["Montmartre evening walk", "Dinner near Sacré-Cœur"],
                    "hotel": "Hotel Le Marais",
                    "meals": ["Local Montmartre restaurant (dinner)"],
                    "transport_notes": "RER C from Paris-Austerlitz to Versailles (45 min)",
                },
                {
                    "day": 5,
                    "date": end.isoformat(),
                    "morning": ["Falafel at L'As du Fallafel", "Shopping in Le Marais"],
                    "afternoon": ["Centre Pompidou", "Pack and check out"],
                    "evening": ["Transfer to CDG airport", "Departure"],
                    "hotel": "Hotel Le Marais (check-out by noon)",
                    "meals": ["L'As du Fallafel (lunch)"],
                    "transport_notes": "RER B to CDG (45 min), arrive 3 hours before flight",
                },
            ],
            "conflicts": [],
        },
        "review_status": {
            "approved": True,
            "conflicts": [],
            "warnings": ["Pre-book Louvre tickets to avoid queues."],
            "retry_reasons": [],
        },
        "pdf_status": {
            "generated": True,
            "file_path": "./outputs/trip_session_test_abc.pdf",
            "error": None,
        },
        "orchestrator_decision": {
            "next_node": "END",
            "reason": "Trip plan approved and PDF generated.",
            "phase": "complete",
        },
        "retry_counts": {},
        "errors": [],
    }


@pytest.fixture
def minimal_prefs() -> dict:
    """Minimal valid trip preferences."""
    start = _future_start(10)
    end = start + timedelta(days=2)
    return {
        "destination": "Tokyo",
        "origin": "London",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "budget_usd": 3000,
        "travelers": 1,
    }


@pytest.fixture
def past_date_prefs() -> dict:
    """Preferences with a start_date in the past — should fail validation."""
    return {
        "destination": "Rome",
        "origin": "Berlin",
        "start_date": "2020-01-01",
        "end_date": "2020-01-05",
        "budget_usd": 2000,
        "travelers": 2,
    }


@pytest.fixture
def empty_itinerary_state(sample_state) -> dict:
    state = dict(sample_state)
    state["itinerary"] = {"days": [], "conflicts": []}
    return state


@pytest.fixture
def over_budget_state(sample_state) -> dict:
    state = dict(sample_state)
    state["budget_summary"] = {
        **sample_state["budget_summary"],
        "total_spent": 6500,   # 30% over the $5000 budget
        "within_budget": False,
    }
    return state


@pytest.fixture
def blocked_guardrail_state(sample_state) -> dict:
    state = dict(sample_state)
    state["guardrail_result"] = {
        "passed": False,
        "reason": "Input contains harmful content.",
        "severity": "block",
        "pii_detected": [],
        "details": {"is_safe": False},
    }
    return state
