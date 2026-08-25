"""Child process for the crash-recovery demo.

Run as: python -m langgraph_agent_lab.crash_child <db_path> <thread_id>

It starts a risky run that pauses at the approval interrupt, writes the pause to
a durable SQLite checkpoint, prints a marker, and exits WITHOUT approving — as if
the process crashed mid-workflow. The parent process then resumes from disk.
"""

from __future__ import annotations

import os
import sys


def main() -> None:
    db_path = sys.argv[1] if len(sys.argv) > 1 else "outputs/crash.sqlite"
    thread_id = sys.argv[2] if len(sys.argv) > 2 else "thread-crash"

    os.environ["LANGGRAPH_INTERRUPT"] = "true"

    from .graph import build_graph
    from .persistence import build_checkpointer
    from .state import Route, Scenario, initial_state

    graph = build_graph(checkpointer=build_checkpointer("sqlite", db_path))
    scenario = Scenario(
        id="crash",
        query="Delete customer account after support verification",
        expected_route=Route.RISKY,
        requires_approval=True,
    )
    config = {"configurable": {"thread_id": thread_id}}
    result = graph.invoke(initial_state(scenario), config=config)

    paused = isinstance(result, dict) and "__interrupt__" in result
    print(f"CHILD_PAUSED={paused}")
    # Exit hard to simulate a crash while awaiting approval; checkpoint is on disk.
    sys.exit(0)


if __name__ == "__main__":
    main()
