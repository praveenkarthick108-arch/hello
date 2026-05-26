from datetime import date
from typing import Optional
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

from src.config import settings
from src.state import TripPlannerState
from src.guardrails import deterministic_guardrails, pii_handler


class TripPreferences(BaseModel):
    destination: str = Field(description="City and country, e.g. 'Goa, India'")
    origin: str = Field(description="Departure city, e.g. 'Bangalore, India'")
    start_date: str = Field(description="Start date in YYYY-MM-DD format")
    end_date: str = Field(description="End date in YYYY-MM-DD format")
    budget_usd: float = Field(gt=0, description="Total budget in USD")
    travelers: int = Field(ge=1, le=20, description="Number of travelers")
    trip_type: str = Field(description="One of: leisure, beach, adventure, business, honeymoon, family")
    dietary_restrictions: list[str] = Field(default_factory=list, description="e.g. ['vegetarian', 'halal']")
    preferred_activities: list[str] = Field(default_factory=list, description="e.g. ['sightseeing', 'nightlife']")
    mobility_needs: str = Field(default="none", description="Special mobility requirements")
    budget_style: str = Field(default="mid", description="One of: luxury, mid, budget")


_SYSTEM = """You are a travel requirements analyst. Extract and normalize trip planning details
from user input. Today is {today}.

Rules:
- Convert any currency to USD (approximate: 1 USD ≈ 83 INR, 1 USD ≈ 0.92 EUR)
- Convert relative dates (e.g. "next week") to absolute YYYY-MM-DD dates
- Infer budget_style: luxury (>$300/night equivalent), budget (<$80/night), mid (everything else)
- Infer trip_type from context: beach/water activities → beach, trekking/camping → adventure, etc.
- If travelers not specified, default to 1
- If no budget given, estimate based on trip_type and duration (budget trips: $100/day/person)
- If you see tokens like [PII_EMAIL_1] or [PII_PHONE_1], treat them as placeholders and ignore them"""

_llm = ChatOpenAI(
    model=settings.openai_model,
    temperature=0,
    api_key=settings.openai_api_key,
)
_chain = (
    ChatPromptTemplate.from_messages([
        ("system", _SYSTEM),
        ("human", "{raw_input}"),
    ])
    | _llm.with_structured_output(TripPreferences)
)


async def user_input_node(state: TripPlannerState) -> dict:
    raw_input = state["raw_input"]

    # Mask PII before sending to the LLM — prevents personal data leakage in API calls
    masked_input, pii_map = pii_handler.mask_pii(raw_input)

    try:
        result: TripPreferences = await _chain.ainvoke({
            "raw_input": masked_input,
            "today": date.today().isoformat(),
        })
        prefs = result.model_dump()

        # Restore PII tokens in location fields (e.g. if the user typed an address as origin)
        for key in ("destination", "origin"):
            if isinstance(prefs.get(key), str):
                prefs[key] = pii_handler.restore_pii(prefs[key], pii_map)

        # Deterministic post-parse validation
        validation = deterministic_guardrails.validate_trip_preferences(prefs)
        if not validation.passed:
            return {
                "trip_preferences": prefs,
                "errors": [f"user_input_agent (validation): {validation.reason}"],
            }
        if validation.severity == "warn":
            return {
                "trip_preferences": prefs,
                "errors": [f"user_input_agent (warning): {validation.reason}"],
            }

        return {"trip_preferences": prefs}

    except Exception as e:
        return {
            "trip_preferences": {"error": str(e), "raw_input": raw_input},
            "errors": [f"user_input_agent: {e}"],
        }
