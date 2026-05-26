"""
Fallback mechanisms for the trip planner:
  LLMFallback    — retry with exponential back-off, then switch to a cheaper model
  SearchFallback — wrap Tavily with timeout + canned mock responses
  AgentFallback  — default structured data when an agent completely fails
"""

import asyncio
import logging
from datetime import date
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)

_FALLBACK_MODEL = "gpt-3.5-turbo"


# ── LLM Fallback ─────────────────────────────────────────────────────────────

class LLMFallback:
    """Retry the primary LLM call; on repeated failure switch to a cheaper model."""

    MAX_RETRIES:      int   = 2
    BASE_DELAY:       float = 1.0    # seconds between retries
    PRIMARY_TIMEOUT:  float = 45.0
    FALLBACK_TIMEOUT: float = 30.0

    @staticmethod
    async def call_with_fallback(
        primary_fn:  Callable[[], Awaitable[Any]],
        fallback_fn: Callable[[], Awaitable[Any]],
        agent_name: str = "unknown",
    ) -> Any:
        """Try primary_fn up to MAX_RETRIES times, then try fallback_fn once."""
        last_error: Exception | None = None

        for attempt in range(LLMFallback.MAX_RETRIES):
            try:
                return await asyncio.wait_for(
                    primary_fn(), timeout=LLMFallback.PRIMARY_TIMEOUT
                )
            except Exception as exc:
                last_error = exc
                logger.warning(
                    f"[{agent_name}] LLM attempt {attempt + 1}/{LLMFallback.MAX_RETRIES} failed: {exc}"
                )
                if attempt < LLMFallback.MAX_RETRIES - 1:
                    await asyncio.sleep(LLMFallback.BASE_DELAY * (attempt + 1))

        logger.warning(
            f"[{agent_name}] Primary model exhausted after {LLMFallback.MAX_RETRIES} attempts. "
            f"Switching to fallback model ({_FALLBACK_MODEL})."
        )
        try:
            return await asyncio.wait_for(
                fallback_fn(), timeout=LLMFallback.FALLBACK_TIMEOUT
            )
        except Exception as exc:
            raise RuntimeError(
                f"[{agent_name}] Both primary and fallback LLM calls failed. "
                f"Last primary error: {last_error}"
            ) from exc


# ── Search Fallback ───────────────────────────────────────────────────────────

class SearchFallback:
    """Wrap a Tavily search call with timeout handling and meaningful mock fallbacks."""

    _MOCKS: dict[str, str] = {
        "transport": (
            "Live search unavailable. Typical transport options: direct flights (2–4 hrs, "
            "$100–$400/person), express trains ($30–$150), intercity buses ($10–$50). "
            "Prices vary by season and booking lead time."
        ),
        "hotel": (
            "Live search unavailable. Typical hotels: budget guesthouses ($30–$60/night), "
            "mid-range hotels ($80–$150/night), luxury resorts ($200–$500+/night). "
            "Book via Booking.com or Hotels.com for live pricing."
        ),
        "places": (
            "Live search unavailable. Common highlights include: historic old town, local food "
            "market, national museum, scenic viewpoint, traditional bazaar. "
            "Check TripAdvisor for destination-specific recommendations."
        ),
    }

    @staticmethod
    async def search(
        query: str,
        search_fn: Callable,
        timeout: float = 25.0,
        context: str = "general",
    ) -> str:
        """Run search_fn with timeout; return mock data string on any failure."""
        loop = asyncio.get_event_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, lambda: search_fn({"query": query})),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            logger.warning(f"[SearchFallback] Timeout ({timeout}s) for query: '{query[:60]}'")
            return SearchFallback._MOCKS.get(
                context,
                f"Search timed out for: {query}. Check travel booking sites directly.",
            )
        except Exception as exc:
            logger.warning(f"[SearchFallback] Error for query '{query[:60]}': {exc}")
            return SearchFallback._MOCKS.get(
                context,
                f"Search unavailable for: {query}. Check travel booking sites directly.",
            )


# ── Agent-level Fallback (default structured responses) ───────────────────────

class AgentFallback:
    """Return sensible default structured data when an agent completely fails."""

    @staticmethod
    def default_transport(prefs: dict) -> dict:
        budget = float(prefs.get("budget_usd", 1000))
        origin = prefs.get("origin", "origin city")
        dest   = prefs.get("destination", "destination")
        return {
            "outbound_options": [
                {
                    "mode": "flight",
                    "operator": "Various airlines",
                    "duration": "varies",
                    "price_usd": round(budget * 0.12, 2),
                    "notes": (
                        f"Fallback estimate for {origin} → {dest}. "
                        "Search actual prices on Google Flights or Skyscanner."
                    ),
                }
            ],
            "return_options": [],
            "recommended": None,
            "estimated_cost_usd": round(budget * 0.25, 2),
            "availability": True,
            "notes": "Transport data unavailable — estimated at 25% of total budget.",
        }

    @staticmethod
    def default_hotel(prefs: dict) -> dict:
        budget       = float(prefs.get("budget_usd", 1000))
        budget_style = prefs.get("budget_style", "mid")
        dest         = prefs.get("destination", "destination")
        stars        = {"luxury": 5, "mid": 3, "budget": 2}.get(budget_style, 3)
        try:
            days = (
                date.fromisoformat(str(prefs["end_date"]))
                - date.fromisoformat(str(prefs["start_date"]))
            ).days
        except Exception:
            days = 3
        hotel_budget = budget * 0.40
        return {
            "options": [],
            "recommended": {
                "name": f"{stars}-star hotel in {dest}",
                "stars": stars,
                "price_per_night_usd": round(hotel_budget / max(days, 1), 2),
                "location": dest,
                "rating": 4.0,
                "amenities": ["WiFi", "Breakfast"],
                "notes": "Fallback estimate — verify actual pricing before booking.",
            },
            "estimated_cost_usd": round(hotel_budget, 2),
            "within_budget": True,
            "stars": stars,
            "notes": "Hotel data unavailable — estimated at 40% of total budget.",
        }

    @staticmethod
    def default_places(prefs: dict) -> dict:
        dest      = prefs.get("destination", "the destination")
        trip_type = prefs.get("trip_type", "leisure")
        return {
            "attractions": [
                {
                    "name": f"Top attractions in {dest}",
                    "category": "sightseeing", "indoor": False,
                    "description": "", "entry_fee_usd": 0, "duration_hours": 2, "rating": 0,
                },
                {
                    "name": f"Historic district of {dest}",
                    "category": "culture", "indoor": False,
                    "description": "", "entry_fee_usd": 0, "duration_hours": 2, "rating": 0,
                },
            ],
            "restaurants": [
                {
                    "name": f"Local cuisine in {dest}",
                    "category": "restaurant", "indoor": True,
                    "description": "", "entry_fee_usd": 0, "duration_hours": 1, "rating": 0,
                },
            ],
            "local_experiences": [
                {
                    "name": f"Cultural tour of {dest}",
                    "category": trip_type, "indoor": False,
                    "description": "", "entry_fee_usd": 0, "duration_hours": 3, "rating": 0,
                },
            ],
            "indoor_options": [
                {
                    "name": f"National Museum of {dest}",
                    "category": "museum", "indoor": True,
                    "description": "", "entry_fee_usd": 0, "duration_hours": 2, "rating": 0,
                },
                {
                    "name": f"Art Gallery in {dest}",
                    "category": "art", "indoor": True,
                    "description": "", "entry_fee_usd": 0, "duration_hours": 2, "rating": 0,
                },
                {
                    "name": "Shopping mall / covered market",
                    "category": "shopping", "indoor": True,
                    "description": "", "entry_fee_usd": 0, "duration_hours": 2, "rating": 0,
                },
            ],
            "outdoor_options": [
                {
                    "name": f"City park in {dest}",
                    "category": "outdoor", "indoor": False,
                    "description": "", "entry_fee_usd": 0, "duration_hours": 2, "rating": 0,
                },
            ],
        }

    @staticmethod
    def default_weather(prefs: dict) -> dict:
        dest = prefs.get("destination", "destination")
        return {
            "daily_forecast": [],
            "summary": (
                f"Weather data unavailable for {dest}. "
                "Check weather.com or a local forecast before travel."
            ),
            "severe_weather": False,
            "rain_days": 0,
        }
