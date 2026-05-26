from langgraph.graph import StateGraph, START, END
from langgraph.types import Send

from src.state import TripPlannerState
from src.config import settings

# Agent node imports
from src.agents.guardrail_agent import guardrail_node
from src.agents.user_input_agent import user_input_node
from src.agents.memory_agent import memory_node
from src.agents.weather_agent import weather_node
from src.agents.transport_agent import transport_node
from src.agents.hotel_agent import hotel_node
from src.agents.places_agent import places_node
from src.agents.budget_agent import budget_node
from src.agents.itinerary_agent import itinerary_node
from src.agents.final_review_agent import final_review_node
from src.agents.pdf_generator_agent import pdf_generator_node


# ── Orchestrator router ───────────────────────────────────────────────────────

def orchestrator_router(state: TripPlannerState) -> str | list[Send]:
    """Pure deterministic routing function — the brain of the system.
    Called after every node completes. Returns the next node name(s) to execute.
    Returning a list of Send objects triggers parallel execution."""

    retries = state.get("retry_counts", {})
    MAX = settings.max_retries_per_agent

    # ── Phase 0: Input guardrails (runs once before anything else) ──
    if not state.get("guardrail_result"):
        return "input_guardrail"

    # If guardrails blocked the request, terminate the pipeline immediately
    if not state.get("guardrail_result", {}).get("passed", True):
        return END

    # ── Phase 1: Validate and normalize user input ──
    if not state.get("trip_preferences"):
        return "user_input_agent"

    # ── Phase 2: Load user memory ──
    if not state.get("user_profile"):
        return "memory_agent"

    # ── Phase 3: Parallel research fan-out ──
    # All four run concurrently via Send API; barrier sync happens automatically
    pending = []
    if not state.get("weather_data"):
        pending.append(Send("weather_agent", state))
    if not state.get("transport_data"):
        pending.append(Send("transport_agent", state))
    if not state.get("hotel_data"):
        pending.append(Send("hotel_agent", state))
    if not state.get("places_data"):
        pending.append(Send("places_agent", state))
    if pending:
        return pending

    # ── Phase 4: Conflict-driven retries (evaluated after research completes) ──
    prefs = state.get("trip_preferences") or {}
    total_budget = float(prefs.get("budget_usd", 0))

    # Rule: hotel estimate too high → retry hotel agent
    hotel = state.get("hotel_data") or {}
    hotel_cost = float(hotel.get("estimated_cost_usd", 0))
    if hotel_cost > total_budget * 0.60 and not hotel.get("within_budget"):
        if retries.get("hotel_agent", 0) < MAX:
            return "hotel_agent"

    # Rule: transport unavailable → retry transport agent
    transport = state.get("transport_data") or {}
    if not transport.get("availability", True):
        if retries.get("transport_agent", 0) < MAX:
            return "transport_agent"

    # Rule: severe weather + no indoor options → retry places agent
    weather = state.get("weather_data") or {}
    places  = state.get("places_data") or {}
    if weather.get("severe_weather") and not places.get("indoor_options"):
        if retries.get("places_agent", 0) < MAX:
            return "places_agent"

    # ── Phase 5: Budget calculation ──
    if not state.get("budget_summary"):
        return "budget_agent"

    # ── Phase 6: Day-wise itinerary ──
    if not state.get("itinerary"):
        return "itinerary_agent"

    # Rule: itinerary has scheduling conflicts → retry itinerary agent
    itinerary = state.get("itinerary") or {}
    if itinerary.get("conflicts") and retries.get("itinerary_agent", 0) < MAX:
        return "itinerary_agent"

    # ── Phase 7: Final review ──
    review = state.get("review_status") or {}

    if not review:
        return "final_review_agent"

    # Rule: review failed → retry the offending agent ONCE, then re-review
    if not review.get("approved", True):
        retry_reasons = review.get("retry_reasons", [])
        agent_map = {
            "hotel":     "hotel_agent",
            "transport": "transport_agent",
            "itinerary": "itinerary_agent",
            "places":    "places_agent",
            "budget":    "budget_agent",
        }
        for reason, agent_name in agent_map.items():
            if reason in retry_reasons and retries.get(agent_name, 0) < 1:
                return agent_name

        # All retries done — re-run the review once to get a fresh result
        reviewed_after_retry = review.get("_retried", False)
        if not reviewed_after_retry:
            return "final_review_agent"

    # ── Phase 8: PDF generation ──
    if not (state.get("pdf_status") or {}).get("generated"):
        return "pdf_generator_agent"

    return END


# ── Graph assembly ────────────────────────────────────────────────────────────

def build_graph() -> StateGraph:
    """Assemble and compile the LangGraph StateGraph."""
    graph = StateGraph(TripPlannerState)

    # Register all agent nodes
    graph.add_node("input_guardrail",    guardrail_node)
    graph.add_node("user_input_agent",   user_input_node)
    graph.add_node("memory_agent",       memory_node)
    graph.add_node("weather_agent",      weather_node)
    graph.add_node("transport_agent",    transport_node)
    graph.add_node("hotel_agent",        hotel_node)
    graph.add_node("places_agent",       places_node)
    graph.add_node("budget_agent",       budget_node)
    graph.add_node("itinerary_agent",    itinerary_node)
    graph.add_node("final_review_agent", final_review_node)
    graph.add_node("pdf_generator_agent",pdf_generator_node)

    # Orchestrator checkpoint: a lightweight pass-through node at entry
    graph.add_node("orchestrator", lambda state: {})

    # Entry point → orchestrator
    graph.add_edge(START, "orchestrator")

    # Hub-and-spoke: every node returns to the orchestrator for the next decision
    all_nodes = [
        "orchestrator",
        "input_guardrail",
        "user_input_agent",
        "memory_agent",
        "weather_agent",
        "transport_agent",
        "hotel_agent",
        "places_agent",
        "budget_agent",
        "itinerary_agent",
        "final_review_agent",
        "pdf_generator_agent",
    ]
    for node_name in all_nodes:
        graph.add_conditional_edges(node_name, orchestrator_router)

    return graph.compile()


# Singleton compiled graph (imported by api/main.py)
_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph
