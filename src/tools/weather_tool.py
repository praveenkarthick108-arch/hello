import httpx
from langchain_core.tools import tool

from src.config import settings

_MOCK_WEATHER = {
    "daily_forecast": [
        {"date": "Day 1", "condition": "Partly Cloudy", "high_c": 28, "low_c": 22, "rain_prob": 20},
        {"date": "Day 2", "condition": "Sunny", "high_c": 30, "low_c": 23, "rain_prob": 5},
        {"date": "Day 3", "condition": "Sunny", "high_c": 31, "low_c": 24, "rain_prob": 5},
        {"date": "Day 4", "condition": "Light Rain", "high_c": 26, "low_c": 21, "rain_prob": 70},
        {"date": "Day 5", "condition": "Partly Cloudy", "high_c": 27, "low_c": 22, "rain_prob": 30},
    ],
    "summary": "Generally warm and pleasant with one rainy day expected.",
    "severe_weather": False,
    "rain_days": 1,
    "mock": True,
}


def _parse_forecast(data: dict) -> dict:
    """Parse OWM 5-day /forecast response into our schema."""
    items = data.get("list", [])
    daily: dict[str, dict] = {}

    for item in items:
        date_str = item["dt_txt"][:10]
        if date_str not in daily:
            daily[date_str] = {
                "date": date_str,
                "condition": item["weather"][0]["description"].title(),
                "high_c": item["main"]["temp_max"],
                "low_c": item["main"]["temp_min"],
                "rain_prob": round(item.get("pop", 0) * 100),
            }

    forecasts = list(daily.values())[:7]
    rain_days = sum(1 for d in forecasts if d["rain_prob"] > 60)
    severe = any(
        kw in d["condition"].lower()
        for d in forecasts
        for kw in ("thunderstorm", "heavy rain", "blizzard", "hurricane")
    )

    return {
        "daily_forecast": forecasts,
        "summary": f"{len(forecasts)}-day forecast for destination.",
        "severe_weather": severe,
        "rain_days": rain_days,
        "mock": False,
    }


@tool
def get_weather(destination: str, start_date: str, end_date: str) -> dict:
    """Get weather forecast for a destination during travel dates.
    Returns daily_forecast, summary, severe_weather flag, and rain_days count."""
    if not settings.openweathermap_api_key:
        return _MOCK_WEATHER

    try:
        with httpx.Client(timeout=10) as client:
            geo_resp = client.get(
                "http://api.openweathermap.org/geo/1.0/direct",
                params={
                    "q": destination,
                    "limit": 1,
                    "appid": settings.openweathermap_api_key,
                },
            )
            geo = geo_resp.json()
            if not geo:
                return _MOCK_WEATHER

            lat, lon = geo[0]["lat"], geo[0]["lon"]
            fc_resp = client.get(
                "https://api.openweathermap.org/data/2.5/forecast",
                params={
                    "lat": lat,
                    "lon": lon,
                    "appid": settings.openweathermap_api_key,
                    "units": "metric",
                    "cnt": 40,
                },
            )
            return _parse_forecast(fc_resp.json())
    except Exception:
        return _MOCK_WEATHER
