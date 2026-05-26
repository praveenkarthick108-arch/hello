import asyncio
from typing import Optional
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI

from src.config import settings
from src.state import TripPlannerState
from src.tools.search_tool import tavily_search
from src.fallbacks import LLMFallback, SearchFallback, AgentFallback

_FALLBACK_MODEL = "gpt-3.5-turbo"


class TransportOption(BaseModel):
    mode: str = Field(description="flight, train, bus, or car")
    operator: str = Field(default="", description="Airline or operator name")
    duration: str = Field(default="", description="Travel duration")
    price_usd: float = Field(default=0, description="Estimated price per person in USD")
    notes: str = Field(default="")


class TransportData(BaseModel):
    outbound_options: list[TransportOption] = Field(default_factory=list)
    return_options: list[TransportOption] = Field(default_factory=list)
    recommended: Optional[TransportOption] = None
    estimated_cost_usd: float = Field(default=0)
    availability: bool = Field(default=True)
    notes: str = Field(default="")


_SYSTEM = """You are a travel transport researcher. Search for transport options between
the origin and destination. Focus on options that fit within the budget.
After searching, return structured data about the best options found.
Estimated transport budget: ~25% of total trip budget."""

_llm_primary  = ChatOpenAI(model=settings.openai_model, temperature=0, api_key=settings.openai_api_key)
_llm_fallback = ChatOpenAI(model=_FALLBACK_MODEL,       temperature=0, api_key=settings.openai_api_key)

_llm_structured_primary  = _llm_primary.with_structured_output(TransportData)
_llm_structured_fallback = _llm_fallback.with_structured_output(TransportData)


async def transport_node(state: TripPlannerState) -> dict:
    prefs = state.get("trip_preferences", {})
    retry_increment = {"transport_agent": 1} if state.get("transport_data") else {}

    origin           = prefs.get("origin", "")
    dest             = prefs.get("destination", "")
    start            = prefs.get("start_date", "")
    end              = prefs.get("end_date", "")
    travelers        = prefs.get("travelers", 1)
    budget           = prefs.get("budget_usd", 1000)
    transport_budget = budget * 0.25

    query = (
        f"cheapest flights or trains from {origin} to {dest} "
        f"departing {start} returning {end} for {travelers} passengers"
    )

    try:
        # Step 1: search with automatic timeout + mock fallback
        search_result = await SearchFallback.search(
            query=query,
            search_fn=tavily_search.invoke,
            timeout=25.0,
            context="transport",
        )

        # Step 2: parse with LLM fallback chain
        parse_prompt = f"""Based on this search result about transport from {origin} to {dest}:

{search_result}

Trip details:
- Dates: {start} to {end}
- Travelers: {travelers}
- Transport budget: ~${transport_budget:.0f} USD total

Extract and structure the transport options. If no specific prices found, estimate based on typical rates.
Mark availability=False only if search clearly states no options exist."""

        result: TransportData = await LLMFallback.call_with_fallback(
            primary_fn  = lambda: _llm_structured_primary.ainvoke(parse_prompt),
            fallback_fn = lambda: _llm_structured_fallback.ainvoke(parse_prompt),
            agent_name  = "transport_agent",
        )

        # Recompute estimated total cost
        if result.recommended and result.recommended.price_usd:
            result.estimated_cost_usd = result.recommended.price_usd * travelers * 2
        elif result.outbound_options:
            cheapest = min((o.price_usd for o in result.outbound_options if o.price_usd), default=0)
            result.estimated_cost_usd = cheapest * travelers * 2

        return {"transport_data": result.model_dump(), "retry_counts": retry_increment}

    except Exception as e:
        fallback = AgentFallback.default_transport(prefs)
        fallback["notes"] = f"Search and parse both failed: {e}. {fallback['notes']}"
        return {
            "transport_data": fallback,
            "retry_counts": retry_increment,
            "errors": [f"transport_agent: {e}"],
        }
