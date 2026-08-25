"""Pytest bootstrap: load .env so LLM-gated tests can see API keys, and isolate
the LANGGRAPH_INTERRUPT env var so HITL/API tests don't leak real-interrupt mode
into the base graph tests (which expect mock auto-approval)."""

import os

import pytest

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


@pytest.fixture(autouse=True)
def _isolate_interrupt_env():
    """Snapshot and restore LANGGRAPH_INTERRUPT around every test."""
    prior = os.environ.get("LANGGRAPH_INTERRUPT")
    yield
    if prior is None:
        os.environ.pop("LANGGRAPH_INTERRUPT", None)
    else:
        os.environ["LANGGRAPH_INTERRUPT"] = prior
