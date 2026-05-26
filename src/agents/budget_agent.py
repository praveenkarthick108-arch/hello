import asyncio
from src.state import TripPlannerState


async def budget_node(state: TripPlannerState) -> dict:
    retry_increment = {"budget_agent": 1} if state.get("budget_summary") else {}
    prefs = state.get("trip_preferences", {})
    transport = state.get("transport_data", {})
    hotel = state.get("hotel_data", {})
    places = state.get("places_data", {})

    total_budget = float(prefs.get("budget_usd", 0) or 0)
    travelers = int(prefs.get("travelers", 1) or 1)

    try:
        from datetime import date
        days = (
            date.fromisoformat(str(prefs.get("end_date", "2025-01-08")))
            - date.fromisoformat(str(prefs.get("start_date", "2025-01-01")))
        ).days
        days = max(days, 1)
    except Exception:
        days = 3

    # Deterministic cost calculation — no LLM needed
    transport_cost = float(transport.get("estimated_cost_usd") or total_budget * 0.25)
    hotel_cost = float(hotel.get("estimated_cost_usd") or total_budget * 0.40)

    activities_cost = sum(
        float(p.get("entry_fee_usd") or 15) * travelers
        for p in places.get("attractions", [])[:5]
    )

    food_cost = days * travelers * 40   # $40/person/day
    misc_cost = total_budget * 0.05
    total_spent = transport_cost + hotel_cost + activities_cost + food_cost + misc_cost
    remaining = total_budget - total_spent
    within_budget = total_spent <= total_budget

    # Static tips — no extra LLM call, no timeout risk
    optimizations: list[str] = []
    if not within_budget:
        over_by = total_spent - total_budget
        optimizations = [
            f"Trip is over budget by ${over_by:.0f}. Consider adjusting the hotel choice.",
            "Look for flight deals 4–6 weeks in advance or choose a train/bus route.",
            "Opt for mid-range stays instead of premium hotels to save on accommodation.",
            "Eat at local restaurants and street food stalls to reduce food costs.",
            "Prioritise 2–3 key attractions instead of visiting everything to save on entry fees.",
        ]

    return {
        "retry_counts": retry_increment,
        "budget_summary": {
            "total_budget": round(total_budget, 2),
            "transport_cost": round(transport_cost, 2),
            "hotel_cost": round(hotel_cost, 2),
            "activities_cost": round(activities_cost, 2),
            "food_cost": round(food_cost, 2),
            "misc_cost": round(misc_cost, 2),
            "total_spent": round(total_spent, 2),
            "remaining": round(remaining, 2),
            "within_budget": within_budget,
            "optimizations": optimizations,
        }
    }
