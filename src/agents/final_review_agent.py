import json
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from src.config import settings
from src.state import TripPlannerState


class ReviewResult(BaseModel):
    approved: bool = Field(description="True if no blocking conflicts found")
    conflicts: list[str] = Field(default_factory=list, description="Blocking issues")
    warnings: list[str] = Field(default_factory=list, description="Non-blocking notes")
    retry_reasons: list[str] = Field(
        default_factory=list,
        description="Which agents to retry: hotel, transport, itinerary, places, budget"
    )


_llm = ChatOpenAI(
    model=settings.openai_model,
    temperature=0,
    api_key=settings.openai_api_key,
)
_llm_structured = _llm.with_structured_output(ReviewResult)

_SYSTEM = """You are a meticulous trip plan quality reviewer. Check the trip plan for:

1. Budget compliance: Does total_spent exceed total_budget? (blocking conflict if yes by >10%)
2. Date consistency: Are itinerary days aligned with start_date to end_date?
3. Hotel-transport alignment: Does hotel check-in match arrival day?
4. Weather-activity alignment: Are outdoor-only activities on heavy rain days?
5. Completeness: Does every trip day have at least one activity?

Return approved=True only if there are NO blocking conflicts.
For each blocking issue, add the responsible agent to retry_reasons (hotel, transport, itinerary).
Warnings are non-blocking (nice-to-fix but not worth retrying)."""


async def final_review_node(state: TripPlannerState) -> dict:
    prefs = state.get("trip_preferences", {})
    budget = state.get("budget_summary", {})
    itinerary = state.get("itinerary", {})
    hotel = state.get("hotel_data", {})
    transport = state.get("transport_data", {})
    weather = state.get("weather_data", {})

    plan_summary = f"""TRIP PLAN SUMMARY:

Destination: {prefs.get('destination')} from {prefs.get('origin')}
Dates: {prefs.get('start_date')} to {prefs.get('end_date')}
Travelers: {prefs.get('travelers')}

BUDGET:
- Total budget: ${budget.get('total_budget', 0):,.0f}
- Total estimated spend: ${budget.get('total_spent', 0):,.0f}
- Within budget: {budget.get('within_budget')}
- Remaining: ${budget.get('remaining', 0):,.0f}

HOTEL:
- Recommended: {json.dumps(hotel.get('recommended', {}))}
- Within budget: {hotel.get('within_budget')}

TRANSPORT:
- Recommended: {json.dumps(transport.get('recommended', {}))}
- Availability: {transport.get('availability')}

WEATHER:
- Severe weather: {weather.get('severe_weather')}
- Rain days: {weather.get('rain_days')}

ITINERARY ({len(itinerary.get('days', []))} days planned):
{json.dumps(itinerary.get('days', []), default=str)[:2000]}

Existing conflicts from itinerary agent: {itinerary.get('conflicts', [])}"""

    # Track whether this is a re-review after retries (to break the loop)
    prior_review = state.get("review_status", {})
    is_re_review = bool(prior_review) and not prior_review.get("approved", True)

    try:
        result: ReviewResult = await _llm_structured.ainvoke([
            SystemMessage(_SYSTEM),
            HumanMessage(plan_summary),
        ])
        output = result.model_dump()
        if is_re_review:
            output["_retried"] = True  # signals orchestrator: no more retries
        return {"review_status": output}
    except Exception as e:
        # On review failure, approve with warning rather than blocking
        return {
            "review_status": {
                "approved": True,
                "conflicts": [],
                "warnings": [f"Review agent failed: {e} — proceeding with plan."],
                "retry_reasons": [],
            },
            "errors": [f"final_review_agent: {e}"],
        }
