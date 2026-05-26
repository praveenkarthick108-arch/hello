from src.state import TripPlannerState
from src.memory.chroma_manager import ChromaManager


async def memory_node(state: TripPlannerState) -> dict:
    prefs = state.get("trip_preferences", {})
    user_id = state["user_id"]

    query = (
        f"trips to {prefs.get('destination', '')} "
        f"budget ${prefs.get('budget_usd', 0)} "
        f"for {prefs.get('travelers', 1)} traveler(s) "
        f"{prefs.get('trip_type', 'leisure')}"
    )

    try:
        chroma = ChromaManager()
        profile = await chroma.retrieve_user_profile(user_id, query)
        return {"user_profile": profile}
    except Exception as e:
        return {
            "user_profile": {"new_user": True, "past_trips": [], "inferred_preferences": {}},
            "errors": [f"memory_agent: {e}"],
        }
