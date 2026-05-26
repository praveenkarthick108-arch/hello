import json
import logging
import uuid
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, BackgroundTasks, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

from src.config import settings
from src.state import initial_state
from src.graph import get_graph
from src.memory.sqlite_manager import (
    init_db,
    create_trip_record,
    update_trip_record,
    get_trip_record,
    get_user_trips,
)


# ── MLflow setup ─────────────────────────────────────────────────────────────

def _setup_mlflow() -> None:
    if not settings.mlflow_enabled:
        return
    try:
        import mlflow
        mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
        mlflow.set_experiment(settings.mlflow_experiment)
        mlflow.openai.autolog()
        logger.info(f"[MLflow] Tracking → {settings.mlflow_tracking_uri}  experiment={settings.mlflow_experiment}")
    except Exception as exc:
        logger.warning(f"[MLflow] Setup failed (non-fatal): {exc}")


def _log_trip_to_mlflow(session_id: str, prefs: dict, eval_report: dict | None) -> None:
    if not settings.mlflow_enabled:
        return
    try:
        import mlflow
        with mlflow.start_run(run_name=session_id):
            # Params — what was planned
            p = prefs or {}
            mlflow.log_params({
                "session_id":  session_id,
                "destination": p.get("destination", ""),
                "origin":      p.get("origin", ""),
                "start_date":  p.get("start_date", ""),
                "end_date":    p.get("end_date", ""),
                "budget_usd":  p.get("budget_usd", 0),
                "travelers":   p.get("travelers", 1),
                "trip_type":   p.get("trip_type", ""),
                "model":       settings.openai_model,
            })

            # Metrics — eval scores
            if eval_report:
                summary = eval_report.get("summary", {})
                if summary.get("overall_avg_score") is not None:
                    mlflow.log_metric("overall_avg_score", summary["overall_avg_score"])
                if summary.get("overall_pass_rate") is not None:
                    mlflow.log_metric("overall_pass_rate", summary["overall_pass_rate"])

                basic = eval_report.get("suites", {}).get("basic", {})
                for r in basic.get("results", []):
                    mlflow.log_metric(f"eval_{r['name']}", r["score"])

            # Artifact — full eval report JSON
            eval_path = Path(f"./eval_reports/eval_{session_id}.json")
            if eval_path.exists():
                mlflow.log_artifact(str(eval_path), artifact_path="eval_reports")

    except Exception as exc:
        logger.warning(f"[MLflow] Logging failed (non-fatal): {exc}")


# ── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    _setup_mlflow()
    yield


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="AI Trip Planner",
    description=(
        "Multi-agent AI trip planning system powered by LangGraph. "
        "Submit a natural language trip request and receive a complete "
        "itinerary with downloadable PDF."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


# ── Request / Response models ─────────────────────────────────────────────────

class TripPlanRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=64, description="Unique user identifier")
    raw_input: str = Field(
        ...,
        min_length=10,
        max_length=2000,
        description=(
            "Natural language trip request. "
            "Example: 'Plan a 5-day Goa trip from Bangalore for 2 people, "
            "budget ₹30,000, beach resort, seafood, flights preferred'"
        ),
    )

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "user_id": "user_123",
                "raw_input": "Plan a 5-day Goa trip from Bangalore for a couple, budget 30000 INR, beach resort, seafood, flights preferred",
            }]
        }
    }


class TripPlanResponse(BaseModel):
    session_id: str
    status: str
    message: str
    pdf_download_url: Optional[str] = None


class TripStatusResponse(BaseModel):
    session_id: str
    user_id: str
    status: str
    current_phase: Optional[str] = None
    trip_preferences: Optional[dict] = None
    budget_summary: Optional[dict] = None
    itinerary: Optional[dict] = None
    review_status: Optional[dict] = None
    pdf_status: Optional[dict] = None
    pdf_download_url: Optional[str] = None
    eval_report_url: Optional[str] = None
    errors: list[str] = []
    created_at: Optional[str] = None


class UserTripsResponse(BaseModel):
    user_id: str
    trips: list[dict]
    total: int


# ── Background task: run the LangGraph graph ─────────────────────────────────

def _save_eval_report(session_id: str, state: dict) -> None:
    """Run basic evals on the completed state and write a JSON report to ./eval_reports/."""
    try:
        from evals.eval_runner import EvaluationRunner
        runner = EvaluationRunner(
            run_basic=True,
            run_ragas=True,
            run_deepeval=True,
            output_dir="./eval_reports",
        )
        runner.evaluate(state, save_report=True)
        logger.info(f"[Evals] Report saved for session {session_id}")
    except Exception as exc:
        logger.warning(f"[Evals] Eval runner failed for session {session_id}: {exc}")


async def run_trip_graph(session_id: str, user_id: str, raw_input: str) -> None:
    graph = get_graph()
    init = initial_state(user_id=user_id, session_id=session_id, raw_input=raw_input)

    # Collected outputs (last-write-wins per key across all node completions)
    trip_prefs = None
    budget = None
    itinerary = None
    review = None
    pdf_path = None
    guardrail_result = None
    weather_data = None
    hotel_data = None
    transport_data = None
    places_data = None
    all_errors: list[str] = []

    try:
        await update_trip_record(session_id, current_phase="starting")

        # Stream node-by-node so we can update current_phase in real time
        async for chunk in graph.astream(init, config={"recursion_limit": 100}):
            for node_name, node_output in chunk.items():
                if node_name in ("__end__", "orchestrator"):
                    continue

                # Update live progress in DB → frontend poll sees it immediately
                await update_trip_record(session_id, current_phase=node_name)

                if not isinstance(node_output, dict):
                    continue

                if node_output.get("trip_preferences"):
                    trip_prefs = node_output["trip_preferences"]
                if node_output.get("budget_summary"):
                    budget = node_output["budget_summary"]
                if node_output.get("itinerary"):
                    itinerary = node_output["itinerary"]
                if node_output.get("review_status"):
                    review = node_output["review_status"]
                if node_output.get("pdf_status", {}).get("file_path"):
                    pdf_path = node_output["pdf_status"]["file_path"]
                if node_output.get("guardrail_result"):
                    guardrail_result = node_output["guardrail_result"]
                if node_output.get("weather_data"):
                    weather_data = node_output["weather_data"]
                if node_output.get("hotel_data"):
                    hotel_data = node_output["hotel_data"]
                if node_output.get("transport_data"):
                    transport_data = node_output["transport_data"]
                if node_output.get("places_data"):
                    places_data = node_output["places_data"]
                if node_output.get("errors"):
                    all_errors.extend(node_output["errors"])

        status = "completed" if pdf_path else "partial"
        await update_trip_record(
            session_id,
            status=status,
            current_phase="done",
            trip_preferences=trip_prefs,
            budget_summary=budget,
            itinerary=itinerary,
            review_status=review,
            pdf_path=pdf_path,
            errors=all_errors,
        )

        # Build final state dict and generate eval report
        # Run in a thread so RAGAS/DeepEval can use asyncio.run() without
        # conflicting with the uvicorn event loop already running here.
        final_state = {
            "session_id": session_id,
            "raw_input": raw_input,
            "trip_preferences": trip_prefs,
            "budget_summary": budget,
            "itinerary": itinerary,
            "review_status": review,
            "guardrail_result": guardrail_result,
            "weather_data": weather_data,
            "hotel_data": hotel_data,
            "transport_data": transport_data,
            "places_data": places_data,
        }
        import asyncio
        import threading

        def _run_in_own_loop():
            # Plain thread — no inherited event loop context from uvicorn.
            # asyncio.run() inside here creates its own fresh loop + task,
            # which is what asyncio.timeout() (used by DeepEval) requires.
            _save_eval_report(session_id, final_state)
            # After evals are written, log everything to MLflow
            eval_path = Path(f"./eval_reports/eval_{session_id}.json")
            eval_report = None
            if eval_path.exists():
                with open(eval_path, "r", encoding="utf-8") as f:
                    eval_report = json.load(f)
            _log_trip_to_mlflow(session_id, trip_prefs, eval_report)

        t = threading.Thread(target=_run_in_own_loop, daemon=True)
        t.start()

    except Exception as e:
        await update_trip_record(
            session_id,
            status="failed",
            current_phase="error",
            errors=[str(e)],
        )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post("/trips", response_model=TripPlanResponse, status_code=202)
async def create_trip(request: TripPlanRequest, background_tasks: BackgroundTasks):
    """Submit a new trip planning request.

    Returns immediately with a `session_id`. Poll `/trips/{session_id}/status`
    to check progress. Download the PDF from `/trips/{session_id}/pdf` when complete.
    """
    session_id = str(uuid.uuid4())

    await create_trip_record(
        session_id=session_id,
        user_id=request.user_id,
        raw_input=request.raw_input,
    )

    background_tasks.add_task(
        run_trip_graph,
        session_id=session_id,
        user_id=request.user_id,
        raw_input=request.raw_input,
    )

    return TripPlanResponse(
        session_id=session_id,
        status="accepted",
        message=(
            f"Trip planning started! Poll GET /trips/{session_id}/status for updates. "
            f"Estimated time: 60–120 seconds."
        ),
    )


@app.get("/trips/{session_id}/status", response_model=TripStatusResponse)
async def get_trip_status(session_id: str):
    """Poll for the current state of a trip planning session."""
    record = await get_trip_record(session_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")

    pdf_url = None
    if record.pdf_path and os.path.exists(record.pdf_path):
        pdf_url = f"/trips/{session_id}/pdf"

    eval_url = None
    if Path(f"./eval_reports/eval_{session_id}.json").exists():
        eval_url = f"/trips/{session_id}/eval"

    return TripStatusResponse(
        session_id=session_id,
        user_id=record.user_id,
        status=record.status,
        current_phase=record.current_phase,
        trip_preferences=record.trip_preferences,
        budget_summary=record.budget_summary,
        itinerary=record.itinerary,
        review_status=record.review_status,
        pdf_status={"generated": bool(record.pdf_path), "file_path": record.pdf_path},
        pdf_download_url=pdf_url,
        eval_report_url=eval_url,
        errors=record.errors or [],
        created_at=record.created_at.isoformat() if record.created_at else None,
    )


@app.get("/trips/{session_id}/pdf")
async def download_pdf(session_id: str):
    """Download the generated trip plan PDF."""
    record = await get_trip_record(session_id)
    if not record:
        raise HTTPException(status_code=404, detail="Session not found.")

    if not record.pdf_path:
        raise HTTPException(
            status_code=404,
            detail="PDF not yet generated. Check /status — planning may still be in progress.",
        )

    if not os.path.exists(record.pdf_path):
        raise HTTPException(status_code=500, detail="PDF file missing on server.")

    filename = f"trip_plan_{session_id[:8]}.pdf"
    return FileResponse(
        path=record.pdf_path,
        media_type="application/pdf",
        filename=filename,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/trips/{session_id}/eval")
async def get_eval_report(session_id: str):
    """Return the evaluation report for a completed trip planning session."""
    path = Path(f"./eval_reports/eval_{session_id}.json")
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail="Eval report not yet available. Trip may still be in progress or evals are pending.",
        )
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


@app.get("/users/{user_id}/trips", response_model=UserTripsResponse)
async def get_user_trip_history(
    user_id: str,
    limit: int = Query(default=10, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
):
    """Retrieve a user's trip planning history."""
    records = await get_user_trips(user_id, limit=limit, offset=offset)
    trips = []
    for r in records:
        trips.append({
            "session_id": r.session_id,
            "status": r.status,
            "destination": (r.trip_preferences or {}).get("destination", ""),
            "start_date": (r.trip_preferences or {}).get("start_date", ""),
            "end_date": (r.trip_preferences or {}).get("end_date", ""),
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "pdf_available": bool(r.pdf_path),
        })
    return UserTripsResponse(user_id=user_id, trips=trips, total=len(trips))


@app.get("/", include_in_schema=False)
async def root():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/docs")


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "version": "1.0.0",
        "model": settings.openai_model,
    }
