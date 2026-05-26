import os
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Absolute path to the project root — stable regardless of working directory
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _abs(path: str) -> str:
    """Resolve a path to absolute, anchored at the project root if relative."""
    if os.path.isabs(path):
        return path
    # Strip leading "./" so os.path.join works cleanly
    return os.path.join(_PROJECT_ROOT, path.lstrip("./").lstrip("\\"))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.path.join(_PROJECT_ROOT, ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM
    openai_api_key: str
    openai_model: str = "gpt-4o-mini"
    openai_temperature: float = 0.1
    embedding_model: str = "text-embedding-3-small"

    # APIs
    tavily_api_key: str
    openweathermap_api_key: str = ""

    # LangSmith tracing
    langsmith_api_key: str = ""
    langchain_project: str = "trip-planner"
    langsmith_tracing: bool = False

    # Storage
    chroma_persist_dir: str = "./chroma_db"
    chroma_collection_name: str = "user_preferences"
    sqlite_url: str = "sqlite+aiosqlite:///./trip_history.db"

    # PDF output
    pdf_output_dir: str = "./outputs"

    # Orchestrator
    max_retries_per_agent: int = 3

    # App
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    debug: bool = False

    @model_validator(mode="after")
    def _resolve_relative_paths(self) -> "Settings":
        """Convert any relative storage paths to absolute, anchored at project root.
        Ensures the server works regardless of the working directory it is launched from."""
        # SQLite URL: sqlite+aiosqlite:///./path  →  sqlite+aiosqlite:////absolute/path
        if "///./" in self.sqlite_url or self.sqlite_url.endswith("///"):
            rel = (
                self.sqlite_url
                .replace("sqlite+aiosqlite:///./", "")
                .replace("sqlite:///./", "")
            )
            self.sqlite_url = f"sqlite+aiosqlite:///{_abs(rel)}"

        if not os.path.isabs(self.chroma_persist_dir):
            self.chroma_persist_dir = _abs(self.chroma_persist_dir)

        if not os.path.isabs(self.pdf_output_dir):
            self.pdf_output_dir = _abs(self.pdf_output_dir)

        # Configure LangSmith tracing — LangGraph reads these from os.environ
        if self.langsmith_tracing and self.langsmith_api_key:
            os.environ["LANGCHAIN_TRACING_V2"] = "true"
            os.environ["LANGCHAIN_API_KEY"] = self.langsmith_api_key
            os.environ["LANGCHAIN_PROJECT"] = self.langchain_project

        return self


settings = Settings()

# Ensure output directories exist at import time
os.makedirs(settings.pdf_output_dir, exist_ok=True)
os.makedirs(settings.chroma_persist_dir, exist_ok=True)
