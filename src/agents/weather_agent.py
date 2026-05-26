import asyncio
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from src.config import settings
from src.state import TripPlannerState
from src.tools.weather_tool import get_weather

_MOCK = {
    "daily_forecast": [{"date": "TBD", "condition": "Sunny", "high_c": 28, "low_c": 20, "rain_prob": 10}],
    "summary": "Weather data unavailable — pleasant conditions assumed.",
    "severe_weather": False,
    "rain_days": 0,
    "mock": True,
}


async def weather_node(state: TripPlannerState) -> dict:
    prefs = state.get("trip_preferences", {})
    destination = prefs.get("destination", "")
    start_date = prefs.get("start_date", "")
    end_date = prefs.get("end_date", "")

    retry_increment = {"weather_agent": 1} if state.get("weather_data") else {}

    try:
        loop = asyncio.get_event_loop()
        result = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: get_weather.invoke({
                    "destination": destination,
                    "start_date": start_date,
                    "end_date": end_date,
                }),
            ),
            timeout=20.0,
        )
        return {"weather_data": result, "retry_counts": retry_increment}
    except asyncio.TimeoutError:
        return {
            "weather_data": {**_MOCK, "summary": "Weather fetch timed out."},
            "retry_counts": retry_increment,
            "errors": ["weather_agent: timeout"],
        }
    except Exception as e:
        return {
            "weather_data": _MOCK,
            "retry_counts": retry_increment,
            "errors": [f"weather_agent: {e}"],
        }
