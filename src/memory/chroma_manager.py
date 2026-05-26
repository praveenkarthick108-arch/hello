import chromadb
from chromadb import PersistentClient
from openai import AsyncOpenAI

from src.config import settings

_openai = AsyncOpenAI(api_key=settings.openai_api_key)


class ChromaManager:
    _instance: "ChromaManager | None" = None

    def __new__(cls) -> "ChromaManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self) -> None:
        self._client = PersistentClient(path=settings.chroma_persist_dir)
        self._collection = self._client.get_or_create_collection(
            name=settings.chroma_collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    async def _embed(self, text: str) -> list[float]:
        response = await _openai.embeddings.create(
            model=settings.embedding_model,
            input=text,
        )
        return response.data[0].embedding

    async def store_trip_result(self, user_id: str, session_id: str, trip_data: dict) -> None:
        """Store a completed trip for future preference retrieval."""
        destination = trip_data.get("destination", "unknown")
        origin = trip_data.get("origin", "unknown")
        trip_type = trip_data.get("trip_type", "leisure")
        budget = trip_data.get("budget_usd", 0)
        travelers = trip_data.get("travelers", 1)
        days = trip_data.get("days", 0)
        activities = ", ".join(trip_data.get("top_activities", [])[:5]) or "various"
        hotel = trip_data.get("hotel_summary", "")

        doc = (
            f"Trip to {destination} from {origin}, {days} days, {trip_type} trip, "
            f"budget ${budget} USD, {travelers} traveler(s). "
            f"Hotel: {hotel}. Activities: {activities}."
        )

        embedding = await self._embed(doc)

        self._collection.upsert(
            ids=[f"{user_id}_{session_id}"],
            embeddings=[embedding],
            documents=[doc],
            metadatas=[{
                "user_id": user_id,
                "destination": destination,
                "budget_usd": float(budget),
                "trip_type": trip_type,
                "travelers": int(travelers),
                "days": int(days),
            }],
        )

    async def retrieve_user_profile(self, user_id: str, query: str) -> dict:
        """Retrieve past trips and infer preferences for the current trip context."""
        count = self._collection.count()
        if count == 0:
            return {"new_user": True, "past_trips": [], "inferred_preferences": {}}

        embedding = await self._embed(query)
        n = min(5, count)

        try:
            results = self._collection.query(
                query_embeddings=[embedding],
                n_results=n,
                where={"user_id": user_id},
                include=["documents", "metadatas", "distances"],
            )
        except Exception:
            return {"new_user": True, "past_trips": [], "inferred_preferences": {}}

        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        if not docs:
            return {"new_user": True, "past_trips": [], "inferred_preferences": {}}

        past_trips = []
        for doc, meta, dist in zip(docs, metas, distances):
            if dist < 0.85:
                past_trips.append({
                    "summary": doc,
                    "metadata": meta,
                    "relevance_score": round(1 - dist, 3),
                })

        inferred = _infer_preferences(past_trips)
        return {
            "new_user": len(past_trips) == 0,
            "past_trips": past_trips,
            "inferred_preferences": inferred,
        }


def _infer_preferences(past_trips: list[dict]) -> dict:
    if not past_trips:
        return {}

    budgets = [t["metadata"].get("budget_usd", 0) for t in past_trips]
    avg_budget = sum(budgets) / len(budgets) if budgets else 0
    destinations = [t["metadata"].get("destination", "") for t in past_trips]

    return {
        "average_budget_usd": round(avg_budget, 2),
        "visited_destinations": list(set(destinations)),
        "trip_count": len(past_trips),
    }
