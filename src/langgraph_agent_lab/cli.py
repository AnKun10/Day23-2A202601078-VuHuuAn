"""CLI for the lab."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
import yaml

from .graph import build_graph
from .metrics import MetricsReport, metric_from_state, summarize_metrics, write_metrics
from .persistence import build_checkpointer
from .report import write_report
from .scenarios import load_scenarios
from .state import initial_state

app = typer.Typer(no_args_is_help=True)


@app.command("run-scenarios")
def run_scenarios(
    config: Annotated[Path, typer.Option("--config")],
    output: Annotated[Path, typer.Option("--output")],
) -> None:
    """Run all grading scenarios and write metrics JSON."""
    cfg = yaml.safe_load(config.read_text(encoding="utf-8"))
    scenarios = load_scenarios(cfg["scenarios_path"])
    checkpointer = build_checkpointer(cfg.get("checkpointer", "memory"), cfg.get("database_url"))
    graph = build_graph(checkpointer=checkpointer)
    metrics = []
    for scenario in scenarios:
        state = initial_state(scenario)
        run_config = {"configurable": {"thread_id": state["thread_id"]}}
        final_state = graph.invoke(state, config=run_config)
        metrics.append(metric_from_state(final_state, scenario.expected_route.value, scenario.requires_approval))
    report = summarize_metrics(metrics)
    write_metrics(report, output)
    if cfg.get("report_path"):
        write_report(report, cfg["report_path"], student=cfg.get("student"))
    typer.echo(f"Wrote metrics to {output}")


@app.command("persist-demo")
def persist_demo(
    output: Annotated[Path, typer.Option("--output")] = Path("outputs/persistence_evidence.txt"),
    db: Annotated[Path, typer.Option("--db")] = Path("outputs/checkpoints.sqlite"),
) -> None:
    """Demonstrate SQLite persistence: run a scenario, then replay its state history.

    Evidence for the persistence/recovery track: a durable SQLite checkpointer, a
    per-run thread_id, and a full checkpoint history that survives a *fresh* graph
    instance (crash-resume: we rebuild the graph and re-read state from disk).
    """
    from .state import Route, Scenario

    scenario = Scenario(
        id="persist_demo", query="How do I reset my password?", expected_route=Route.SIMPLE
    )
    thread_id = f"thread-{scenario.id}"
    run_config = {"configurable": {"thread_id": thread_id}}

    # Run once with a SQLite checkpointer (writes checkpoints to disk).
    checkpointer = build_checkpointer("sqlite", str(db))
    graph = build_graph(checkpointer=checkpointer)
    final = graph.invoke(initial_state(scenario), config=run_config)

    # Crash-resume: build a BRAND NEW graph + checkpointer over the same DB/thread
    # and read the persisted state back — proving it survived the first process.
    graph2 = build_graph(checkpointer=build_checkpointer("sqlite", str(db)))
    resumed = graph2.get_state(run_config)
    history = list(graph2.get_state_history(run_config))

    lines = [
        "=== SQLite Persistence Evidence ===",
        f"thread_id: {thread_id}",
        f"db file: {db}",
        f"final route: {final.get('route')} | final_answer set: {bool(final.get('final_answer'))}",
        f"checkpoints in history: {len(history)}",
        f"resumed state has answer: {bool(resumed.values.get('final_answer'))}",
        f"resumed next nodes: {resumed.next}",
        "",
        "Checkpoint trail (newest → oldest):",
    ]
    for i, snap in enumerate(history):
        step = snap.metadata.get("step") if snap.metadata else "?"
        writes = list((snap.metadata or {}).get("writes", {}) or {})
        lines.append(f"  [{i}] step={step} next={snap.next} wrote={writes}")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    typer.echo(f"Wrote persistence evidence to {output} ({len(history)} checkpoints)")


@app.command("parallel-demo")
def parallel_demo(
    output: Annotated[Path, typer.Option("--output")] = Path("outputs/parallel_evidence.txt"),
) -> None:
    """Extension: fan out to concurrent tool workers via Send(), then fan in."""
    from .parallel import SUBTASKS, build_parallel_graph

    graph = build_parallel_graph()
    result = graph.invoke({"query": "Prepare a full order summary for order 12345"})
    results = result.get("tool_results", [])
    lines = [
        "=== Parallel Fan-out / Fan-in Evidence ===",
        f"subtasks dispatched (concurrent): {SUBTASKS}",
        f"results gathered: {len(results)}",
        *[f"  - {r}" for r in results],
        "",
        f"final_answer: {result.get('final_answer')}",
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    typer.echo(f"Wrote parallel evidence to {output} ({len(results)} concurrent results)")


@app.command("hitl-demo")
def hitl_demo(
    approve: Annotated[bool, typer.Option("--approve/--reject")] = True,
    output: Annotated[Path, typer.Option("--output")] = Path("outputs/hitl_evidence.txt"),
) -> None:
    """Extension: real human-in-the-loop via interrupt() + Command(resume=...)."""
    from .extensions import run_hitl_demo

    res = run_hitl_demo(approve=approve)
    lines = [
        "=== Real HITL (interrupt / resume) Evidence ===",
        f"decision: {'APPROVE' if approve else 'REJECT'}",
        f"paused at interrupt: {res['paused_at_interrupt']}",
        f"paused next nodes: {res['paused_next_nodes']}",
        f"interrupt payload: {res['interrupt_payload']}",
        f"human decision: {res['human_decision']}",
        f"resumed route: {res['resumed_route']}",
        f"resumed approval: {res['resumed_approval']}",
        f"resumed final_answer: {res['resumed_final_answer']}",
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    typer.echo(f"Wrote HITL evidence to {output} (paused={res['paused_at_interrupt']})")


@app.command("timetravel-demo")
def timetravel_demo(
    output: Annotated[Path, typer.Option("--output")] = Path("outputs/timetravel_evidence.txt"),
) -> None:
    """Extension: replay the graph forward from an earlier checkpoint."""
    from .extensions import run_timetravel_demo

    res = run_timetravel_demo()
    lines = [
        "=== Time-travel (state history replay) Evidence ===",
        f"original route: {res['original_route']} | "
        f"answer present: {res['original_answer_present']}",
        f"checkpoints in history: {res['checkpoints']}",
        f"replayed forward from step: {res['replayed_from_step']}",
        f"replay produced answer: {res['replay_answer_present']}",
        "",
        "History trail (newest → oldest):",
        *[f"  [{s['idx']}] step={s['step']} next={s['next']}" for s in res["history_trail"]],
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    typer.echo(f"Wrote time-travel evidence to {output} ({res['checkpoints']} checkpoints)")


@app.command("crash-demo")
def crash_demo(
    output: Annotated[Path, typer.Option("--output")] = Path("outputs/crash_evidence.txt"),
    db: Annotated[Path, typer.Option("--db")] = Path("outputs/crash.sqlite"),
) -> None:
    """Extension: crash recovery across REAL processes.

    A child process pauses at the approval interrupt then exits (simulated crash);
    this parent process resumes the workflow from the SQLite checkpoint.
    """
    import os
    import subprocess
    import sys

    thread_id = "thread-crash"
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(db) + suffix)
        if p.exists():
            p.unlink()

    # Process A: start the risky run; it pauses at interrupt, then the process dies.
    child = subprocess.run(
        [sys.executable, "-m", "langgraph_agent_lab.crash_child", str(db), thread_id],
        capture_output=True,
        text=True,
    )
    child_marker = child.stdout.strip().splitlines()[-1] if child.stdout.strip() else "(no output)"

    # Process B (this process): a FRESH graph resumes from disk — proving durability.
    os.environ["LANGGRAPH_INTERRUPT"] = "true"
    from langgraph.types import Command

    graph = build_graph(checkpointer=build_checkpointer("sqlite", str(db)))
    config = {"configurable": {"thread_id": thread_id}}
    before = graph.get_state(config)
    resumed = graph.invoke(
        Command(resume={
            "approved": True,
            "reviewer": "human-after-restart",
            "comment": "resumed post-crash",
        }),
        config=config,
    )

    lines = [
        "=== Crash Recovery (across processes) Evidence ===",
        f"child process (writer, then died): {child_marker}",
        f"parent read paused state from disk → next nodes: {list(before.next)}",
        f"parent route recovered: {before.values.get('route')}",
        "parent resumed with human approval →",
        f"  final route: {resumed.get('route')}",
        f"  final_answer set: {bool(resumed.get('final_answer'))}",
        f"  approval reviewer: {(resumed.get('approval') or {}).get('reviewer')}",
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    typer.echo(f"Wrote crash-recovery evidence to {output}")


@app.command("diagram")
def diagram(
    output: Annotated[Path, typer.Option("--output")] = Path("outputs/graph_diagram.mmd"),
) -> None:
    """Export the compiled graph as a Mermaid diagram."""
    graph = build_graph(checkpointer=build_checkpointer("memory"))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(graph.get_graph().draw_mermaid(), encoding="utf-8")
    typer.echo(f"Wrote Mermaid diagram to {output}")


@app.command("serve")
def serve(
    host: Annotated[str, typer.Option("--host")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port")] = 8000,
) -> None:
    """Launch the FastAPI HITL console backend (serves the built UI if present)."""
    import uvicorn

    uvicorn.run("langgraph_agent_lab.api:app", host=host, port=port)


@app.command("validate-metrics")
def validate_metrics(metrics: Annotated[Path, typer.Option("--metrics")]) -> None:
    """Validate metrics JSON schema for grading."""
    payload = json.loads(metrics.read_text(encoding="utf-8"))
    report = MetricsReport.model_validate(payload)
    if report.total_scenarios < 6:
        raise typer.BadParameter("Expected at least 6 scenarios")
    typer.echo(f"Metrics valid. success_rate={report.success_rate:.2%}")


if __name__ == "__main__":
    app()
