"""Report generation helper.

Renders a full markdown lab report from MetricsReport data, following the
structure of reports/lab_report_template.md.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .metrics import MetricsReport


def render_report(metrics: MetricsReport, student: dict[str, Any] | None = None) -> str:
    """Render a complete lab report (markdown) from metrics data.

    `student` (optional) fills the identity header, e.g.
    {"name": ..., "id": ..., "date": ..., "repo": ...}.
    """
    lines: list[str] = []
    add = lines.append

    add("# Day 08 Lab Report — LangGraph Agentic Orchestration\n")

    if student:
        add("## 0. Student\n")
        add("| Field | Value |")
        add("|---|---|")
        for key in ("name", "id", "date", "repo"):
            if student.get(key):
                add(f"| {key.capitalize()} | {student[key]} |")
        add("")

    # 1. Summary
    add("## 1. Metrics summary\n")
    add("| Metric | Value |")
    add("|---|---:|")
    add(f"| Total scenarios | {metrics.total_scenarios} |")
    add(f"| Success rate | {metrics.success_rate:.0%} |")
    add(f"| Avg nodes visited | {metrics.avg_nodes_visited:.1f} |")
    add(f"| Total retries | {metrics.total_retries} |")
    add(f"| Total interrupts (approvals) | {metrics.total_interrupts} |")
    add(f"| Resume success | {metrics.resume_success} |\n")

    # 2. Per-scenario results
    add("## 2. Per-scenario results\n")
    add("| Scenario | Expected | Actual | Success | Retries | Interrupts | Approval req/obs |")
    add("|---|---|---|:---:|---:|---:|:---:|")
    for m in metrics.scenario_metrics:
        ok = "✅" if m.success else "❌"
        approval = f"{m.approval_required}/{m.approval_observed}"
        add(
            f"| {m.scenario_id} | {m.expected_route} | {m.actual_route} | {ok} "
            f"| {m.retry_count} | {m.interrupt_count} | {approval} |"
        )
    add("")

    # 3. Architecture
    add("## 3. Architecture\n")
    add(
        "A single `StateGraph(AgentState)` with 11 nodes. `intake → classify` are fixed; "
        "`classify` branches via `route_after_classify` into five paths (simple, tool, "
        "missing_info, risky, error). The `tool → evaluate → [retry ↔ tool]` cycle forms a "
        "**bounded retry loop** (`route_after_retry` checks `attempt < max_attempts`, else "
        "escalates to `dead_letter`). Risky requests pass through "
        "`risky_action → approval → route_after_approval`. **Every path terminates at "
        "`finalize → END`.**\n"
    )
    add("**State schema — reducers:**\n")
    add("| Field(s) | Reducer | Why |")
    add("|---|---|---|")
    add(
        "| messages, tool_results, errors, events | append (`add`) "
        "| audit trail; never lose history |"
    )
    add(
        "| route, risk_level, attempt, evaluation_result, approval, proposed_action, "
        "pending_question | overwrite | only the latest value matters for the current decision |\n"
    )

    # 4. Failure analysis
    add("## 4. Failure analysis\n")
    add(
        "1. **Transient tool failure / unbounded retry.** `tool_node` simulates errors on the "
        "`error` route; `evaluate_node` flags `needs_retry`; `route_after_retry` bounds the loop "
        "by `max_attempts`. Without that bound the graph would loop forever — the dead-letter "
        "node is the third safety layer.\n"
    )
    add(
        "2. **Risky action executed without approval.** Refund/delete/email requests are routed "
        "to `risky_action → approval` *before* any tool executes. Only an `approved` decision "
        "reaches `tool`; a rejection is diverted to `clarify`, so a side-effecting action can "
        "never run un-reviewed.\n"
    )

    # 5. Graph diagram
    add("## 5. Graph diagram\n")
    add("```mermaid")
    add("graph TD;")
    add("  START --> intake --> classify;")
    add("  classify -. simple .-> answer;")
    add("  classify -. tool .-> tool;")
    add("  classify -. missing_info .-> clarify;")
    add("  classify -. risky .-> risky_action;")
    add("  classify -. error .-> retry;")
    add("  tool --> evaluate;")
    add("  evaluate -. success .-> answer;")
    add("  evaluate -. needs_retry .-> retry;")
    add("  retry -. attempt<max .-> tool;")
    add("  retry -. attempt>=max .-> dead_letter;")
    add("  risky_action --> approval;")
    add("  approval -. approved .-> tool;")
    add("  approval -. rejected .-> clarify;")
    add("  answer --> finalize;")
    add("  clarify --> finalize;")
    add("  dead_letter --> finalize;")
    add("  finalize --> END;")
    add("```")
    add("(Full auto-generated diagram: `outputs/graph_diagram.mmd`.)\n")

    # 6. Persistence
    add("## 6. Persistence / recovery\n")
    add(
        "The graph compiles with a checkpointer and each scenario runs under its own "
        "`thread_id` (`thread-<scenario_id>`), so state is snapshotted per super-step. "
        "The SQLite checkpointer persists those snapshots to disk, enabling "
        "`get_state_history()` replay and crash-resume across process restarts.\n"
    )
    add(
        "**Evidence** (`outputs/persistence_evidence.txt`, from `cli persist-demo`): a "
        "*fresh* graph instance built over the same SQLite DB reads back the completed "
        "state (final answer present) and its full 6-checkpoint history — proving the "
        "state survived the original process.\n"
    )

    # 7. Extensions completed
    add("## 7. Extensions completed\n")
    add("All Phase-5 extension tracks are implemented and verified (evidence in `outputs/`):\n")
    add("| Extension | Where | Evidence / command |")
    add("|---|---|---|")
    add(
        "| Parallel fan-out / fan-in (`Send()`) | `parallel.py` | "
        "`cli parallel-demo` → `outputs/parallel_evidence.txt` |"
    )
    add(
        "| Real HITL (`interrupt()` + `Command(resume)`) | `approval_node`, `extensions.py` | "
        "`cli hitl-demo --approve/--reject` → `outputs/hitl_evidence.txt` |"
    )
    add(
        "| Time-travel replay (`get_state_history`) | `extensions.py` | "
        "`cli timetravel-demo` → `outputs/timetravel_evidence.txt` |"
    )
    add(
        "| Crash recovery across processes | `crash_child.py`, `cli.crash-demo` | "
        "`cli crash-demo` → `outputs/crash_evidence.txt` |"
    )
    add(
        "| SQLite persistence (WAL) | `persistence.py` | "
        "`cli persist-demo` → `outputs/persistence_evidence.txt` |"
    )
    add(
        "| Graph diagram (Mermaid) | `cli.diagram` | "
        "`cli diagram` → `outputs/graph_diagram.mmd` |"
    )
    add(
        "| LLM-as-judge (evaluate) | `nodes.evaluate_node` | "
        "enable with `LAB_LLM_JUDGE=true` |"
    )
    add(
        "| **Ant Design HITL console** (FastAPI + React 18 + antd 5) | `api.py`, `ui/` | "
        "`cli serve` → screenshots in `docs/screenshots/` |\n"
    )
    add(
        "The Ant Design console is the human interface for the real-HITL track: submitting "
        "a risky ticket pauses the graph at `interrupt()`; the reviewer approves/rejects and "
        "the graph resumes via `Command(resume=...)`. See "
        "`docs/screenshots/ui-approval.png` (pending approval) and "
        "`docs/screenshots/ui-completed.png` (resumed & completed).\n"
    )

    # 8. Improvement plan
    add("## 8. Improvement plan\n")
    add(
        "Real HITL, the Ant Design console, persistence, time-travel, crash recovery and "
        "parallel fan-out are already done. With one more day I would: (a) replace the "
        "checkpointer with Postgres for multi-worker durability and add authentication to "
        "the approval console, (b) add exponential backoff + jitter to the retry loop and "
        "surface per-node latency in `metrics.json`, (c) turn on the LLM-as-judge "
        "(`LAB_LLM_JUDGE=true`) with a confidence threshold and a self-repair retry prompt, "
        "and (d) stream node-by-node progress to the UI over WebSockets instead of polling.\n"
    )

    return "\n".join(lines)


def write_report(
    metrics: MetricsReport,
    output_path: str | Path,
    student: dict[str, Any] | None = None,
) -> None:
    """Write the rendered report to a file."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(metrics, student=student), encoding="utf-8")
