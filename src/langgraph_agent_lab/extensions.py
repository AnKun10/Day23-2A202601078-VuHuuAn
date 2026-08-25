"""Extension helpers: real HITL (interrupt/resume) and time-travel replay.

Kept separate from the graded core so the base graph stays lean. Each helper
returns a plain dict so the CLI can serialize it to an evidence file.
"""

from __future__ import annotations

import os
from typing import Any

from .graph import build_graph
from .persistence import build_checkpointer
from .state import Route, Scenario, initial_state


def _interrupt_payload(result: dict[str, Any]) -> Any | None:
    """Extract the interrupt value from an invoke result, if the graph paused."""
    interrupts = result.get("__interrupt__") if isinstance(result, dict) else None
    if not interrupts:
        return None
    first = interrupts[0]
    return getattr(first, "value", first)


def run_hitl_demo(approve: bool = True, db: str = "outputs/hitl.sqlite") -> dict[str, Any]:
    """Real human-in-the-loop: the graph pauses at approval via interrupt(), then
    a human decision resumes it with Command(resume=...).

    Returns evidence for both the pause and the resumed outcome.
    """
    from langgraph.types import Command

    prior = os.environ.get("LANGGRAPH_INTERRUPT")
    os.environ["LANGGRAPH_INTERRUPT"] = "true"
    try:
        graph = build_graph(checkpointer=build_checkpointer("sqlite", db))
        scenario = Scenario(
            id=f"hitl_{'approve' if approve else 'reject'}",
            query="Refund this customer and send confirmation email",
            expected_route=Route.RISKY,
            requires_approval=True,
        )
        config = {"configurable": {"thread_id": f"thread-{scenario.id}"}}

        # 1) Run until the graph pauses at the approval interrupt.
        paused = graph.invoke(initial_state(scenario), config=config)
        payload = _interrupt_payload(paused)
        snapshot = graph.get_state(config)

        # 2) A human resumes with a decision.
        decision = {
            "approved": approve,
            "reviewer": "human-demo",
            "comment": "decided via HITL demo",
        }
        resumed = graph.invoke(Command(resume=decision), config=config)
    finally:
        if prior is None:
            os.environ.pop("LANGGRAPH_INTERRUPT", None)
        else:
            os.environ["LANGGRAPH_INTERRUPT"] = prior

    return {
        "paused_at_interrupt": payload is not None,
        "interrupt_payload": payload,
        "paused_next_nodes": list(snapshot.next),
        "human_decision": decision,
        "resumed_route": resumed.get("route"),
        "resumed_final_answer": resumed.get("final_answer"),
        "resumed_approval": resumed.get("approval"),
    }


def run_timetravel_demo(db: str = "outputs/timetravel.sqlite") -> dict[str, Any]:
    """Time travel: run a scenario, walk its checkpoint history, then replay
    forward from an earlier checkpoint (before the `answer` node).
    """
    graph = build_graph(checkpointer=build_checkpointer("sqlite", db))
    scenario = Scenario(
        id="timetravel",
        query="Please lookup order status for order 999",
        expected_route=Route.TOOL,
    )
    config = {"configurable": {"thread_id": "thread-timetravel"}}

    original = graph.invoke(initial_state(scenario), config=config)
    history = list(graph.get_state_history(config))

    # Find the checkpoint whose *next* step is the answer node, and replay from it.
    replay_from = next((s for s in history if s.next == ("answer",)), None)
    replayed = graph.invoke(None, config=replay_from.config) if replay_from else None

    trail = []
    for i, snap in enumerate(history):
        step = snap.metadata.get("step") if snap.metadata else None
        trail.append({"idx": i, "step": step, "next": list(snap.next)})

    return {
        "original_route": original.get("route"),
        "original_answer_present": bool(original.get("final_answer")),
        "checkpoints": len(history),
        "history_trail": trail,
        "replayed_from_step": (replay_from.metadata or {}).get("step") if replay_from else None,
        "replay_answer_present": bool(replayed.get("final_answer")) if replayed else False,
    }
