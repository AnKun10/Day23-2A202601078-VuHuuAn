"""Tests for the extension features.

The parallel fan-out test needs no LLM. The HITL test is gated behind an API key
(like the graph smoke tests) because resuming runs classify_node/answer_node.
"""

import importlib.util
import os

import pytest

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("langgraph") is None, reason="langgraph not installed"
)

_HAS_KEY = bool(
    os.getenv("GEMINI_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
)


def test_parallel_fan_out_fans_in():
    """Send() dispatches N concurrent workers that fan in via the add reducer."""
    from langgraph_agent_lab.parallel import SUBTASKS, build_parallel_graph

    graph = build_parallel_graph()
    result = graph.invoke({"query": "summarize order 123"})
    assert len(result["tool_results"]) == len(SUBTASKS)
    assert "Aggregated" in result["final_answer"]
    # every subtask contributed exactly one result
    for sub in SUBTASKS:
        assert any(f"[{sub}]" in r for r in result["tool_results"])


@pytest.mark.skipif(not _HAS_KEY, reason="No LLM API key configured")
def test_hitl_interrupt_and_resume_approve():
    from langgraph_agent_lab.extensions import run_hitl_demo

    res = run_hitl_demo(approve=True, db="outputs/test_hitl.sqlite")
    assert res["paused_at_interrupt"] is True
    assert res["paused_next_nodes"] == ["approval"]
    assert res["resumed_route"] == "risky"
    assert res["resumed_approval"]["approved"] is True
    assert res["resumed_final_answer"]


@pytest.mark.skipif(not _HAS_KEY, reason="No LLM API key configured")
def test_hitl_reject_routes_to_clarify():
    from langgraph_agent_lab.extensions import run_hitl_demo

    res = run_hitl_demo(approve=False, db="outputs/test_hitl_reject.sqlite")
    assert res["paused_at_interrupt"] is True
    assert res["resumed_approval"]["approved"] is False
    # a rejected risky action must still terminate with a customer-facing message
    assert res["resumed_final_answer"]
