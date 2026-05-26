from src.state import TripPlannerState
from src.tools.pdf_tool import generate_pdf
from src.memory.chroma_manager import ChromaManager


async def pdf_generator_node(state: TripPlannerState) -> dict:
    try:
        file_path = generate_pdf(state)

        # Store trip in ChromaDB for future memory retrieval
        prefs = state.get("trip_preferences", {})
        itinerary = state.get("itinerary", {})
        places = state.get("places_data", {})

        top_activities = [
            p.get("name", "") for p in places.get("attractions", [])[:5]
        ]
        hotel_name = ""
        hotel_data = state.get("hotel_data", {})
        if hotel_data.get("recommended"):
            hotel_name = hotel_data["recommended"].get("name", "")

        try:
            start = prefs.get("start_date", "")
            end = prefs.get("end_date", "")
            from datetime import date
            days = (date.fromisoformat(str(end)) - date.fromisoformat(str(start))).days
        except Exception:
            days = len(itinerary.get("days", []))

        chroma = ChromaManager()
        await chroma.store_trip_result(
            user_id=state["user_id"],
            session_id=state["session_id"],
            trip_data={
                **prefs,
                "days": days,
                "hotel_summary": hotel_name,
                "top_activities": top_activities,
            },
        )

        return {"pdf_status": {"generated": True, "file_path": file_path, "error": None}}

    except Exception as e:
        return {
            "pdf_status": {"generated": False, "file_path": None, "error": str(e)},
            "errors": [f"pdf_generator_agent: {e}"],
        }
