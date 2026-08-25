"""Extension: parallel fan-out / fan-in using LangGraph `Send()`.

Demonstrates concurrent tool execution — the classic LangGraph advantage over a
linear chain. `plan` fans out one `Send` per subtask; the workers run
concurrently and each appends to `tool_results` (an `add`-reducer field, which is
how fan-in is aggregated); `gather` synthesizes the combined result.

This is an isolated graph so the graded main graph in `graph.py` stays untouched.
"""

from __future__ import annotations

from operator import add
from typing import Annotated, Any, TypedDict

from .state import make_event

# Subtasks a single support query is decomposed into and dispatched concurrently.
SUBTASKS = ["inventory", "pricing", "shipping"]


class ParallelState(TypedDict, total=False):
    query: str
    subtask: str                                   # per-worker payload (via Send)
    tool_results: Annotated[list[str], add]        # fan-in aggregation point
    messages: Annotated[list[str], add]
    events: Annotated[list[dict[str, Any]], add]
    final_answer: str


def build_parallel_graph(checkpointer: Any | None = None):
    """Build a fan-out/fan-in graph: plan → (worker × N concurrently) → gather."""
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import Send

    def plan_node(state: ParallelState) -> dict:
        return {
            "messages": [f"plan:fanout×{len(SUBTASKS)}"],
            "events": [make_event("plan", "completed", f"fan out to {len(SUBTASKS)} workers")],
        }

    def dispatch(state: ParallelState) -> list:
        """Return one Send per subtask → workers execute concurrently."""
        query = state.get("query", "")
        return [Send("worker", {"query": query, "subtask": s}) for s in SUBTASKS]

    def worker_node(state: ParallelState) -> dict:
        subtask = state.get("subtask", "?")
        query = state.get("query", "")
        return {
            "tool_results": [f"OK[{subtask}]: result for '{query[:30]}'"],
            "events": [
                make_event("worker", "completed", f"worker '{subtask}' finished", subtask=subtask)
            ],
        }

    def gather_node(state: ParallelState) -> dict:
        results = state.get("tool_results", []) or []
        return {
            "final_answer": f"Aggregated {len(results)} parallel tool results: "
            + "; ".join(results),
            "messages": [f"gather:{len(results)}"],
            "events": [make_event("gather", "completed", f"gathered {len(results)} results")],
        }

    builder = StateGraph(ParallelState)
    builder.add_node("plan", plan_node)
    builder.add_node("worker", worker_node)
    builder.add_node("gather", gather_node)
    builder.add_edge(START, "plan")
    # Conditional edge that returns Send objects → fan-out. Path list is for drawing.
    builder.add_conditional_edges("plan", dispatch, ["worker"])
    builder.add_edge("worker", "gather")   # all worker branches join at gather
    builder.add_edge("gather", END)
    return builder.compile(checkpointer=checkpointer)
