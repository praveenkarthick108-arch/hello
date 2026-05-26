import json
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from src.config import settings
from src.state import TripPlannerState


class DayPlan(BaseModel):
    day: int
    date: str
    morning: list[str] = Field(default_factory=list)
    afternoon: list[str] = Field(default_factory=list)
    evening: list[str] = Field(default_factory=list)
    hotel: str = Field(default="")
    meals: list[str] = Field(default_factory=list)
    transport_notes: str = Field(default="")


class Itinerary(BaseModel):
    days: list[DayPlan] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)


_llm = ChatOpenAI(
    model=settings.openai_model,
    temperature=0.3,
    api_key=settings.openai_api_key,
)
_llm_structured = _llm.with_structured_output(Itinerary)

_SYSTEM = """You are an expert travel itinerary planner. Create a detailed day-wise itinerary
that is realistic, balanced, and enjoyable. Distribute activities sensibly across days.
- Day 1: arrival + nearby/easy activities
- Last day: check-out + departure-friendly activities
- Mix indoor and outdoor activities
- Account for travel time between locations
- Include specific meal recommendations tied to restaurants found
- Note any scheduling conflicts in the conflicts list"""


async def itinerary_node(state: TripPlannerState) -> dict:
    prefs = state.get("trip_preferences", {})
    weather = state.get("weather_data", {})
    transport = state.get("transport_data", {})
    hotel = state.get("hotel_data", {})
    places = state.get("places_data", {})
    budget = state.get("budget_summary", {})
    retry_increment = {"itinerary_agent": 1} if state.get("itinerary") else {}

    dest = prefs.get("destination", "")
    origin = prefs.get("origin", "")
    start = prefs.get("start_date", "")
    end = prefs.get("end_date", "")
    trip_type = prefs.get("trip_type", "leisure")
    travelers = prefs.get("travelers", 1)
    dietary = prefs.get("dietary_restrictions", [])

    hotel_name = ""
    if hotel.get("recommended"):
        hotel_name = hotel["recommended"].get("name", "")

    attractions = [p.get("name", "") for p in places.get("attractions", [])[:8]]
    restaurants = [p.get("name", "") for p in places.get("restaurants", [])[:6]]
    experiences = [p.get("name", "") for p in places.get("local_experiences", [])[:4]]
    rain_days = weather.get("rain_days", 0)
    indoor = [p.get("name", "") for p in places.get("indoor_options", [])[:4]]
    forecast = weather.get("daily_forecast", [])

    human_msg = f"""Create a day-wise itinerary for this trip:

TRIP DETAILS:
- Route: {origin} → {dest}
- Dates: {start} to {end}
- Travelers: {travelers}, Trip type: {trip_type}
- Dietary restrictions: {', '.join(dietary) or 'none'}

ACCOMMODATION:
- Hotel: {hotel_name or 'TBD'}

TRANSPORT:
- Outbound: {transport.get('recommended', {}).get('mode', 'TBD')} on {start}
- Return: similar transport on {end}

PLACES TO VISIT (prioritize based on trip type):
Attractions: {', '.join(attractions)}
Restaurants: {', '.join(restaurants)}
Experiences: {', '.join(experiences)}
Indoor options (for rain): {', '.join(indoor)}

WEATHER:
- Expected rain days: {rain_days}
- Forecast: {json.dumps(forecast[:5])}

BUDGET NOTE:
- Activities budget: ${budget.get('activities_cost', 0):.0f} total
- Food budget: ${budget.get('food_cost', 0):.0f} total

Generate a complete itinerary. For dates, use consecutive dates starting from {start}.
Flag any conflicts (e.g., activity timings overlap, budget exceeded)."""

    try:
        result: Itinerary = await _llm_structured.ainvoke([
            SystemMessage(_SYSTEM),
            HumanMessage(human_msg),
        ])
        return {"itinerary": result.model_dump(), "retry_counts": retry_increment}
    except Exception as e:
        return {
            "itinerary": {"days": [], "conflicts": [f"Itinerary generation failed: {e}"]},
            "retry_counts": retry_increment,
            "errors": [f"itinerary_agent: {e}"],
        }
