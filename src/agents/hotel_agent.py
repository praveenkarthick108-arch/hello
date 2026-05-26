import asyncio
from typing import Optional
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI

from src.config import settings
from src.state import TripPlannerState
from src.tools.search_tool import tavily_search
from src.fallbacks import LLMFallback, SearchFallback, AgentFallback

_FALLBACK_MODEL = "gpt-3.5-turbo"


class HotelOption(BaseModel):
    name: str = Field(default="", description="Hotel name")
    stars: int = Field(default=3, ge=1, le=5)
    price_per_night_usd: float = Field(default=0)
    location: str = Field(default="")
    rating: float = Field(default=0.0, ge=0, le=5)
    amenities: list[str] = Field(default_factory=list)
    notes: str = Field(default="")


class HotelData(BaseModel):
    options: list[HotelOption] = Field(default_factory=list)
    recommended: Optional[HotelOption] = None
    estimated_cost_usd: float = Field(default=0, description="Total cost for full stay")
    within_budget: bool = Field(default=True)
    stars: int = Field(default=3)
    notes: str = Field(default="")


_llm_primary  = ChatOpenAI(model=settings.openai_model, temperature=0, api_key=settings.openai_api_key)
_llm_fallback = ChatOpenAI(model=_FALLBACK_MODEL,       temperature=0, api_key=settings.openai_api_key)

_llm_structured_primary  = _llm_primary.with_structured_output(HotelData)
_llm_structured_fallback = _llm_fallback.with_structured_output(HotelData)


async def hotel_node(state: TripPlannerState) -> dict:
    prefs = state.get("trip_preferences", {})
    retry_increment = {"hotel_agent": 1} if state.get("hotel_data") else {}

    dest         = prefs.get("destination", "")
    start        = prefs.get("start_date", "")
    end          = prefs.get("end_date", "")
    travelers    = prefs.get("travelers", 1)
    budget       = prefs.get("budget_usd", 1000)
    budget_style = prefs.get("budget_style", "mid")
    trip_type    = prefs.get("trip_type", "leisure")

    hotel_budget = budget * 0.40
    try:
        from datetime import date as dt
        days = (dt.fromisoformat(str(end)) - dt.fromisoformat(str(start))).days
    except Exception:
        days = 3
    per_night_budget = hotel_budget / max(days, 1)

    style_map   = {"luxury": "5-star luxury", "mid": "3-4 star", "budget": "budget guesthouse"}
    style_label = style_map.get(budget_style, "3-4 star")

    query = (
        f"{style_label} hotels in {dest} "
        f"check-in {start} check-out {end} "
        f"for {travelers} guests under ${per_night_budget:.0f} per night "
        f"near {trip_type} attractions"
    )

    try:
        # Step 1: search with automatic timeout + mock fallback
        search_result = await SearchFallback.search(
            query=query,
            search_fn=tavily_search.invoke,
            timeout=25.0,
            context="hotel",
        )

        # Step 2: parse with LLM fallback chain
        parse_prompt = f"""Based on this search about hotels in {dest}:

{search_result}

Trip details:
- Stay: {start} to {end} ({days} nights)
- Travelers: {travelers}
- Hotel budget: ~${hotel_budget:.0f} USD total (${per_night_budget:.0f}/night)
- Preferred style: {style_label}
- Trip type: {trip_type}

Extract hotel options and mark within_budget=True if the recommended option fits the budget.
Set estimated_cost_usd to the total stay cost for the recommended hotel."""

        result: HotelData = await LLMFallback.call_with_fallback(
            primary_fn  = lambda: _llm_structured_primary.ainvoke(parse_prompt),
            fallback_fn = lambda: _llm_structured_fallback.ainvoke(parse_prompt),
            agent_name  = "hotel_agent",
        )

        # Recompute total stay cost from recommended
        if result.recommended and result.recommended.price_per_night_usd:
            result.estimated_cost_usd = result.recommended.price_per_night_usd * days
            result.within_budget      = result.estimated_cost_usd <= hotel_budget
        elif not result.estimated_cost_usd:
            result.estimated_cost_usd = hotel_budget

        return {"hotel_data": result.model_dump(), "retry_counts": retry_increment}

    except Exception as e:
        fallback = AgentFallback.default_hotel(prefs)
        fallback["notes"] = f"Hotel search and parse both failed: {e}. {fallback['notes']}"
        return {
            "hotel_data": fallback,
            "retry_counts": retry_increment,
            "errors": [f"hotel_agent: {e}"],
        }
