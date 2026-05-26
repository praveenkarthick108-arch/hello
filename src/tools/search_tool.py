from langchain_core.tools import tool
from tavily import TavilyClient

from src.config import settings

_client: TavilyClient | None = None


def _get_client() -> TavilyClient:
    global _client
    if _client is None:
        _client = TavilyClient(api_key=settings.tavily_api_key)
    return _client


@tool
def tavily_search(query: str, max_results: int = 5) -> str:
    """Search the web for travel information including flights, hotels, places, and restaurants.
    Use specific queries like 'cheap hotels in Paris under $100 per night' or
    'flights from Bangalore to Goa in June 2025'."""
    try:
        client = _get_client()
        response = client.search(
            query=query,
            search_depth="basic",
            max_results=min(max_results, 5),
            include_raw_content=False,
        )
        results = []
        for r in response.get("results", []):
            snippet = r.get("content", "")[:600]
            results.append(f"**{r.get('title', 'Result')}**\n{snippet}")

        return "\n\n---\n\n".join(results) if results else "No results found."
    except Exception as e:
        return f"Search failed: {e}"
