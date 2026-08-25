"""FastAPI backend for the Ant Design HITL console.

This server IS the "real HITL" extension: it runs the graph with
`LANGGRAPH_INTERRUPT=true`, so any risky request pauses at the approval node via
`interrupt()`. The UI shows the pending action; approving/rejecting resumes the
graph with `Command(resume=...)`. State is durable in SQLite, so pending
approvals survive a server restart.
"""

from __future__ import annotations

import os
import threading
import uuid
from pathlib import Path
from typing import Any

# Enable real interrupts BEFORE the graph/nodes are imported/used.
os.environ.setdefault("LANGGRAPH_INTERRUPT", "true")

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .graph import build_graph
from .persistence import build_checkpointer
from .state import Scenario, initial_state

_DB = os.getenv("LAB_API_DB", "outputs/api_runs.sqlite")
_lock = threading.Lock()
_graph = build_graph(checkpointer=build_checkpointer("sqlite", _DB))

# thread_id -> {"query": str, "order": int}
_runs: dict[str, dict[str, Any]] = {}
_counter = 0

EXAMPLES = [
    {"label": "Simple question", "query": "How do I reset my password?"},
    {"label": "Tool lookup", "query": "Please lookup order status for order 12345"},
    {"label": "Missing info", "query": "Can you fix it?"},
    {"label": "Risky · refund", "query": "Refund this customer and send confirmation email"},
    {"label": "Risky · delete", "query": "Delete customer account after support verification"},
    {"label": "System error", "query": "Timeout failure while processing request"},
]

app = FastAPI(title="LangGraph Agent — HITL Console")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class NewRun(BaseModel):
    query: str


class Decision(BaseModel):
    approved: bool
    reviewer: str = "human"
    comment: str = ""


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def _pending_interrupt(thread_id: str) -> Any | None:
    """Return the pending interrupt payload for a paused run, else None."""
    snap = _graph.get_state(_config(thread_id))
    for task in snap.tasks:
        for it in getattr(task, "interrupts", None) or []:
            return getattr(it, "value", it)
    return None


def _summary(thread_id: str) -> dict[str, Any]:
    snap = _graph.get_state(_config(thread_id))
    values = snap.values or {}
    pending = _pending_interrupt(thread_id)
    if pending is not None:
        status = "awaiting_approval"
    elif values.get("final_answer"):
        status = "completed"
    else:
        status = "running"
    return {
        "thread_id": thread_id,
        "query": _runs.get(thread_id, {}).get("query", values.get("query", "")),
        "order": _runs.get(thread_id, {}).get("order", 0),
        "route": values.get("route", ""),
        "risk_level": values.get("risk_level", ""),
        "status": status,
        "proposed_action": pending.get("proposed_action") if isinstance(pending, dict) else None,
        "final_answer": values.get("final_answer"),
        "approval": values.get("approval"),
        "nodes_visited": len(values.get("events", []) or []),
        "attempt": values.get("attempt", 0),
    }


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "interrupt": os.getenv("LANGGRAPH_INTERRUPT"), "db": _DB}


@app.get("/api/examples")
def examples() -> list[dict]:
    return EXAMPLES


@app.get("/api/graph")
def graph_diagram() -> dict:
    return {"mermaid": _graph.get_graph().draw_mermaid()}


@app.get("/api/runs")
def list_runs() -> list[dict]:
    return sorted((_summary(tid) for tid in _runs), key=lambda r: r["order"], reverse=True)


@app.get("/api/runs/{thread_id}")
def get_run(thread_id: str) -> dict:
    if thread_id not in _runs:
        raise HTTPException(404, "run not found")
    return _summary(thread_id)


@app.post("/api/runs")
def create_run(body: NewRun) -> dict:
    global _counter
    query = body.query.strip()
    if not query:
        raise HTTPException(422, "query must not be empty")
    thread_id = f"run-{uuid.uuid4().hex[:8]}"
    with _lock:
        _counter += 1
        _runs[thread_id] = {"query": query, "order": _counter}
        scenario = Scenario(id=thread_id, query=query, expected_route="simple")
        state = initial_state(scenario)
        state["query"] = query
        _graph.invoke(state, config=_config(thread_id))
    return _summary(thread_id)


@app.post("/api/runs/{thread_id}/decision")
def decide(thread_id: str, body: Decision) -> dict:
    from langgraph.types import Command

    if thread_id not in _runs:
        raise HTTPException(404, "run not found")
    if _pending_interrupt(thread_id) is None:
        raise HTTPException(409, "run is not awaiting approval")
    with _lock:
        _graph.invoke(
            Command(resume=body.model_dump()),
            config=_config(thread_id),
        )
    return _summary(thread_id)


# Serve the built Ant Design UI if present (production single-server mode).
_UI_DIST = Path(__file__).resolve().parents[2] / "ui" / "dist"
if _UI_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(_UI_DIST), html=True), name="ui")
