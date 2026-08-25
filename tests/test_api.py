"""HITL API tests (FastAPI). Gated behind an LLM key since runs call the LLM."""

import importlib.util
import os

import pytest

pytestmark = [
    pytest.mark.skipif(importlib.util.find_spec("fastapi") is None, reason="fastapi not installed"),
    pytest.mark.skipif(
        not (os.getenv("GEMINI_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("ANTHROPIC_API_KEY")),
        reason="No LLM API key configured",
    ),
]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LAB_API_DB", str(tmp_path / "api_test.sqlite"))
    import importlib

    import langgraph_agent_lab.api as api_module

    importlib.reload(api_module)  # rebuild graph against the temp DB
    from fastapi.testclient import TestClient

    return TestClient(api_module.app)


def test_simple_run_completes(client):
    r = client.post("/api/runs", json={"query": "How do I reset my password?"}).json()
    assert r["status"] == "completed"
    assert r["route"] == "simple"
    assert r["final_answer"]


def test_risky_run_pauses_then_resumes(client):
    created = client.post(
        "/api/runs", json={"query": "Refund this customer and send confirmation email"}
    ).json()
    assert created["status"] == "awaiting_approval"
    assert created["route"] == "risky"
    assert created["proposed_action"]

    tid = created["thread_id"]
    decided = client.post(
        f"/api/runs/{tid}/decision",
        json={"approved": True, "reviewer": "tester", "comment": "ok"},
    ).json()
    assert decided["status"] == "completed"
    assert decided["final_answer"]
    assert decided["approval"]["approved"] is True


def test_decision_on_non_pending_run_conflicts(client):
    r = client.post("/api/runs", json={"query": "How do I reset my password?"}).json()
    resp = client.post(
        f"/api/runs/{r['thread_id']}/decision", json={"approved": True}
    )
    assert resp.status_code == 409
