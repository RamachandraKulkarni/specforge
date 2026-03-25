"""FastAPI localhost server — REST API + SSE streaming for pipeline control."""

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from specforge.orchestrator.pipeline import Pipeline
from specforge.utils.file_manager import FileManager
from specforge.utils.logger import configure_logging, get_logger
from specforge.utils.progress import ProgressTracker

load_dotenv()
configure_logging()
log = get_logger()

app = FastAPI(title="SpecForge", version="2.0.0", description="Automated UI Spec Generation Pipeline")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Global pipeline state ──────────────────────────────────────────────────────

_state: dict[str, Any] = {
    "status": "idle",          # idle | running | stopping | complete | error
    "run_id": None,
    "progress": None,
    "cost_summary": {},
    "error": None,
}
_tracker: ProgressTracker | None = None
_pipeline_task: asyncio.Task | None = None
_file_manager = FileManager(os.getenv("OUTPUT_DIR", "./output"))


# ── Config helpers ─────────────────────────────────────────────────────────────

def _load_config() -> dict:
    config_path = os.getenv("SPECFORGE_CONFIG", "config.yaml")
    if Path(config_path).exists():
        with open(config_path, "r") as f:
            return yaml.safe_load(f) or {}
    return {}


# ── Models ─────────────────────────────────────────────────────────────────────

class StartRequest(BaseModel):
    config_override: dict | None = None
    base_url: str | None = None
    credentials: str | None = None  # natural-language: "user: foo@bar.com, pass: abc123"


# ── Pipeline runner ────────────────────────────────────────────────────────────

async def _run_pipeline(config: dict, tracker: ProgressTracker):
    global _state
    try:
        pipeline = Pipeline(config, progress_callback=tracker.emit)
        result = await pipeline.run()
        _state["status"] = "complete"
        _state["cost_summary"] = pipeline.ai.cost_tracker.summary() if pipeline.ai else {}
        tracker.emit("pipeline_complete", {
            "run_id": pipeline.run_id,
            "cost": _state["cost_summary"].get("total_usd", 0),
        })
        log.info("pipeline_complete", run_id=pipeline.run_id)
    except asyncio.CancelledError:
        _state["status"] = "idle"
        _state["error"] = "Pipeline cancelled"
        tracker.emit("pipeline_error", {"error": "Pipeline manually stopped. API calls aborted."})
        log.info("pipeline_cancelled")
    except Exception as e:
        _state["status"] = "error"
        _state["error"] = str(e)
        tracker.emit("pipeline_error", {"error": str(e)})
        log.error("pipeline_error", error=str(e))


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "version": "2.0.0"}


@app.post("/api/pipeline/start")
async def start_pipeline(req: StartRequest, background_tasks: BackgroundTasks):
    global _state, _tracker, _pipeline_task

    if _state["status"] == "running":
        raise HTTPException(status_code=409, detail="Pipeline already running")

    config = _load_config()
    if req.config_override:
        def deep_update(d, u):
            for k, v in u.items():
                if isinstance(v, dict) and k in d and isinstance(d[k], dict):
                    deep_update(d[k], v)
                else:
                    d[k] = v
        deep_update(config, req.config_override)
    if req.base_url:
        config.setdefault("target", {})["base_url"] = req.base_url

    # Credentials: UI input takes priority, then fall back to env vars
    if req.credentials:
        config["_raw_credentials"] = req.credentials  # Haiku parses this inside the pipeline
    else:
        config["_credentials"] = {
            "username": os.getenv("SF_USERNAME", ""),
            "password": os.getenv("SF_PASSWORD", ""),
        }

    _tracker = ProgressTracker()
    _state["status"] = "running"
    _state["error"] = None
    _state["progress"] = None

    _pipeline_task = asyncio.create_task(_run_pipeline(config, _tracker))
    log.info("pipeline_started")
    return {"status": "started", "run_id": _state.get("run_id")}


@app.post("/api/pipeline/stop")
async def stop_pipeline():
    global _state, _pipeline_task
    if _state["status"] != "running":
        raise HTTPException(status_code=409, detail="Pipeline is not running")
    
    _state["status"] = "stopping"
    
    if _pipeline_task and not _pipeline_task.done():
        _pipeline_task.cancel()
        
    _state["status"] = "idle"
    if _tracker:
        _tracker.emit("pipeline_error", {"error": "Pipeline manually stopped by user. API calls aborted."})
        
    return {"status": "stopped"}


@app.get("/api/pipeline/status")
async def get_status():
    return {
        "status": _state["status"],
        "run_id": _state.get("run_id"),
        "cost_summary": _state.get("cost_summary", {}),
        "error": _state.get("error"),
    }


@app.get("/api/pipeline/progress")
async def pipeline_progress():
    """SSE stream of pipeline progress events."""
    async def event_generator():
        if _tracker is None:
            yield {"event": "idle", "data": json.dumps({"status": "no_run"})}
            return

        while _state["status"] in ("running", "stopping"):
            event = await _tracker.next_event(timeout=1.0)
            if event:
                yield {
                    "event": event.event,
                    "data": json.dumps(event.data),
                }
        yield {"event": "complete", "data": json.dumps({"status": _state["status"]})}

    return EventSourceResponse(event_generator())


@app.get("/api/pipeline/history")
async def get_history():
    if _tracker is None:
        return []
    return _tracker.get_history()


@app.get("/api/runs")
async def list_runs():
    return _file_manager.list_runs()


@app.get("/api/runs/{run_id}/spec")
async def get_spec(run_id: str):
    spec = _file_manager.read_spec(run_id)
    if spec is None:
        raise HTTPException(status_code=404, detail="Spec not found")
    return spec


@app.get("/api/runs/{run_id}/cost")
async def get_run_cost(run_id: str):
    cost = _file_manager.read_cost_report(run_id)
    if cost is None:
        raise HTTPException(status_code=404, detail="Cost report not found")
    return cost


@app.get("/api/runs/{run_id}/intermediate/{filename}")
async def get_intermediate(run_id: str, filename: str):
    data = _file_manager.read_intermediate(run_id, filename)
    if data is None:
        raise HTTPException(status_code=404, detail="File not found")
    return data


@app.get("/api/costs")
async def get_costs():
    return _state.get("cost_summary", {})


@app.get("/api/config")
async def get_config():
    config = _load_config()
    # Strip credentials before returning
    if "target" in config and "auth" in config["target"]:
        config["target"]["auth"].pop("credentials", None)
    return config
