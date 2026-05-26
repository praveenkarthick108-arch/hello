from typing import TypedDict, Annotated
import operator


def merge_dicts(left: dict | None, right: dict | None) -> dict:
    """Merge two dicts. Right takes precedence on key conflicts.
    Safe for parallel branches — each branch writes different keys."""
    if left is None:
        return right or {}
    if right is None:
        return left or {}
    return {**left, **right}


def increment_retries(left: dict | None, right: dict | None) -> dict:
    """Add retry counts rather than overwriting them.
    Nodes always return {agent_name: 1}; this accumulates the total."""
    merged = dict(left or {})
    for k, v in (right or {}).items():
        merged[k] = merged.get(k, 0) + v
    return merged


class TripPlannerState(TypedDict):
    # --- Session identity (set once, no reducer needed) ---
    user_id: str
    session_id: str
    raw_input: str

    # --- Phase 1: Validated trip requirements ---
    trip_preferences: Annotated[dict, merge_dicts]
    # Keys: destination, origin, start_date, end_date, budget_usd,
    #       travelers, trip_type, dietary_restrictions, preferred_activities,
    #       mobility_needs, budget_style (luxury|mid|budget)

    # --- Phase 2: User memory ---
    user_profile: Annotated[dict, merge_dicts]
    # Keys: new_user, past_trips (list), inferred_preferences (dict)

    # --- Phase 3: Parallel research outputs ---
    weather_data: Annotated[dict, merge_dicts]
    # Keys: daily_forecast (list), summary, severe_weather (bool), rain_days (int)

    transport_data: Annotated[dict, merge_dicts]
    # Keys: outbound_options (list), return_options (list), recommended (dict),
    #       estimated_cost_usd (float), availability (bool), notes (str)

    hotel_data: Annotated[dict, merge_dicts]
    # Keys: options (list), recommended (dict), estimated_cost_usd (float),
    #       within_budget (bool), stars (int), notes (str)

    places_data: Annotated[dict, merge_dicts]
    # Keys: attractions (list), restaurants (list), local_experiences (list),
    #       indoor_options (list), outdoor_options (list)

    # --- Phase 4: Derived outputs ---
    budget_summary: Annotated[dict, merge_dicts]
    # Keys: total_budget, transport_cost, hotel_cost, activities_cost,
    #       food_cost, misc_cost, total_spent, remaining, within_budget,
    #       optimizations (list of tip strings)

    itinerary: Annotated[dict, merge_dicts]
    # Keys: days (list of day objects), conflicts (list of strings)
    # Day object: {day, date, morning, afternoon, evening, hotel, meals, transport_notes}

    # --- Phase 0: Input guardrail result ---
    guardrail_result: Annotated[dict, merge_dicts]
    # Keys: passed (bool), reason (str), severity (str), pii_detected (list), details (dict)

    # --- Phase 5: Review and output ---
    review_status: Annotated[dict, merge_dicts]
    # Keys: approved (bool), conflicts (list), warnings (list), retry_reasons (list)

    pdf_status: Annotated[dict, merge_dicts]
    # Keys: generated (bool), file_path (str|None), error (str|None)

    # --- Orchestrator control ---
    orchestrator_decision: Annotated[dict, merge_dicts]
    # Keys: next_node (str), reason (str), phase (str)

    retry_counts: Annotated[dict, increment_retries]
    # Keys: hotel_agent, transport_agent, places_agent, itinerary_agent, budget_agent
    # Always return {agent_name: 1} from node — reducer accumulates the total

    errors: Annotated[list, operator.add]
    # Append-only error log from any agent or tool


def initial_state(user_id: str, session_id: str, raw_input: str) -> TripPlannerState:
    """Create a fresh state with all fields initialized to empty defaults."""
    return TripPlannerState(
        user_id=user_id,
        session_id=session_id,
        raw_input=raw_input,
        guardrail_result={},
        trip_preferences={},
        user_profile={},
        weather_data={},
        transport_data={},
        hotel_data={},
        places_data={},
        budget_summary={},
        itinerary={},
        review_status={},
        pdf_status={},
        orchestrator_decision={},
        retry_counts={},
        errors=[],
    )
