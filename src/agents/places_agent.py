import asyncio
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI

from src.config import settings
from src.state import TripPlannerState
from src.tools.search_tool import tavily_search
from src.fallbacks import LLMFallback, SearchFallback, AgentFallback

_FALLBACK_MODEL = "gpt-3.5-turbo"


class PlaceItem(BaseModel):
    name: str = Field(default="")
    category: str = Field(default="", description="museum, beach, temple, restaurant, etc.")
    description: str = Field(default="")
    entry_fee_usd: float = Field(default=0)
    duration_hours: float = Field(default=2)
    indoor: bool = Field(default=False)
    rating: float = Field(default=0.0)


class PlacesData(BaseModel):
    attractions: list[PlaceItem] = Field(default_factory=list, description="Top tourist spots")
    restaurants: list[PlaceItem] = Field(default_factory=list, description="Best dining options")
    local_experiences: list[PlaceItem] = Field(default_factory=list, description="Local unique experiences")
    indoor_options: list[PlaceItem] = Field(default_factory=list, description="Indoor activities for bad weather")
    outdoor_options: list[PlaceItem] = Field(default_factory=list, description="Outdoor activities")


_llm_primary  = ChatOpenAI(model=settings.openai_model, temperature=0, api_key=settings.openai_api_key)
_llm_fallback = ChatOpenAI(model=_FALLBACK_MODEL,       temperature=0, api_key=settings.openai_api_key)

_llm_structured_primary  = _llm_primary.with_structured_output(PlacesData)
_llm_structured_fallback = _llm_fallback.with_structured_output(PlacesData)


async def places_node(state: TripPlannerState) -> dict:
    prefs   = state.get("trip_preferences", {})
    weather = state.get("weather_data", {})
    retry_increment = {"places_agent": 1} if state.get("places_data") else {}

    dest       = prefs.get("destination", "")
    trip_type  = prefs.get("trip_type", "leisure")
    activities = prefs.get("preferred_activities", [])
    dietary    = prefs.get("dietary_restrictions", [])
    has_rain   = weather.get("rain_days", 0) > 0

    queries = [
        f"top tourist attractions and things to do in {dest} {trip_type}",
        f"best local food restaurants in {dest}" + (f" {' '.join(dietary)}" if dietary else ""),
    ]
    if has_rain:
        queries.append(f"indoor activities museums galleries {dest} rainy day")

    try:
        # Run searches in parallel; each uses SearchFallback for timeout + mock handling
        search_tasks = [
            SearchFallback.search(
                query=q,
                search_fn=tavily_search.invoke,
                timeout=20.0,
                context="places",
            )
            for q in queries
        ]
        results = await asyncio.gather(*search_tasks, return_exceptions=True)
        combined = "\n\n---\n\n".join(r for r in results if isinstance(r, str))

        parse_prompt = f"""Based on these search results about {dest}:

{combined}

Trip details:
- Trip type: {trip_type}
- Preferred activities: {', '.join(activities) or 'general sightseeing'}
- Dietary restrictions: {', '.join(dietary) or 'none'}
- Rainy days expected: {has_rain}

Extract and categorize places. For each place include: name, category, brief description,
entry fee (0 if free), indoor=True if it's an indoor venue.
Ensure indoor_options list has at least 3 entries if rainy days > 0."""

        result: PlacesData = await LLMFallback.call_with_fallback(
            primary_fn  = lambda: _llm_structured_primary.ainvoke(parse_prompt),
            fallback_fn = lambda: _llm_structured_fallback.ainvoke(parse_prompt),
            agent_name  = "places_agent",
        )
        return {"places_data": result.model_dump(), "retry_counts": retry_increment}

    except Exception as e:
        fallback = AgentFallback.default_places(prefs)
        return {
            "places_data": fallback,
            "retry_counts": retry_increment,
            "errors": [f"places_agent: {e}"],
        }
