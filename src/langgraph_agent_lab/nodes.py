"""Node functions for the LangGraph workflow.

Each function receives AgentState and returns a partial state update dict.
Do NOT mutate input state — return new values only.

LLM REQUIREMENT:
- classify_node MUST use a real LLM call (structured output for intent classification)
- answer_node MUST use a real LLM call (grounded response generation)
- evaluate_node SHOULD use LLM-as-judge (bonus points; heuristic acceptable for base score)
"""

from __future__ import annotations

import os
import time
from typing import Literal

from pydantic import BaseModel, Field

from .llm import get_llm
from .state import AgentState, make_event


# ─── EXAMPLE: working node (provided for reference) ──────────────────
def intake_node(state: AgentState) -> dict:
    """Normalize raw query. This node is provided as a working example."""
    query = state.get("query", "").strip()
    return {
        "query": query,
        "messages": [f"intake:{query[:40]}"],
        "events": [make_event("intake", "completed", "query normalized")],
    }


# ─── Structured-output schema for classification ─────────────────────
class Classification(BaseModel):
    """Forced structured output for classify_node."""

    route: Literal["simple", "tool", "missing_info", "risky", "error"] = Field(
        ..., description="The single best route for the support ticket."
    )
    reason: str = Field("", description="One short sentence justifying the route.")


_CLASSIFY_SYSTEM = """You are a support-ticket triage classifier. Read the user's message \
and choose exactly ONE route. Apply this priority order when a message could fit more \
than one route — pick the HIGHEST that applies:

1. risky        — actions with side effects: refunds, deletions, cancellations, sending
                  emails, resetting/charging accounts, anything that MUTATES data or money.
2. tool         — read-only information lookups: order status, tracking, search, "look up",
                  "check status of ...". No side effects, but needs a tool/data source.
3. missing_info — vague or incomplete requests with no actionable target
                  (e.g. "can you fix it?", "help", "it's broken").
4. error        — the message describes a SYSTEM failure: timeout, crash, outage,
                  "cannot recover", service unavailable, exception.
5. simple       — a general question answerable directly with no tool or action
                  (e.g. "how do I reset my password?").

Return only the route and a brief reason."""


def classify_node(state: AgentState) -> dict:
    """Classify the query into a route using an LLM with structured output."""
    query = state.get("query", "")
    started = time.perf_counter()
    llm = get_llm()
    classifier = llm.with_structured_output(Classification)
    result: Classification = classifier.invoke(
        [
            ("system", _CLASSIFY_SYSTEM),
            ("human", f"Support ticket:\n{query}"),
        ]
    )
    route = result.route
    risk_level = "high" if route == "risky" else "low"
    latency_ms = int((time.perf_counter() - started) * 1000)
    return {
        "route": route,
        "risk_level": risk_level,
        "messages": [f"classify:{route}"],
        "events": [
            make_event(
                "classify",
                "completed",
                f"route={route} ({result.reason})",
                latency_ms=latency_ms,
                risk_level=risk_level,
            )
        ],
    }


def tool_node(state: AgentState) -> dict:
    """Execute a mock tool call with transient-failure simulation.

    For the `error` route we return a failing result while attempt < 2 so the
    retry loop is exercised, then succeed. Other routes succeed immediately.
    """
    route = state.get("route", "")
    attempt = state.get("attempt", 0)
    query = state.get("query", "")

    if route == "error" and attempt < 2:
        result = f"ERROR: transient tool failure on attempt {attempt} for query: {query[:60]}"
        event = make_event("tool", "failed", "mock tool returned transient error", attempt=attempt)
    else:
        result = f"OK: tool executed successfully (attempt {attempt}) → data for '{query[:60]}'"
        event = make_event("tool", "completed", "mock tool succeeded", attempt=attempt)

    return {
        "tool_results": [result],
        "messages": [f"tool:{'error' if result.startswith('ERROR') else 'ok'}"],
        "events": [event],
    }


def evaluate_node(state: AgentState) -> dict:
    """Evaluate the latest tool result — the retry-loop gate.

    Uses a fast, deterministic heuristic (presence of an ERROR marker) which is
    reliable for grading. Set LAB_LLM_JUDGE=true to enable the LLM-as-judge
    bonus path.
    """
    tool_results = state.get("tool_results", []) or []
    latest = tool_results[-1] if tool_results else ""

    if os.getenv("LAB_LLM_JUDGE", "").lower() == "true" and latest:
        evaluation_result = _llm_judge(state.get("query", ""), latest)
    else:
        evaluation_result = "needs_retry" if "ERROR" in latest.upper() else "success"

    return {
        "evaluation_result": evaluation_result,
        "messages": [f"evaluate:{evaluation_result}"],
        "events": [
            make_event("evaluate", "completed", f"evaluation={evaluation_result}")
        ],
    }


class _Judgement(BaseModel):
    satisfactory: bool = Field(..., description="True if the tool result answers the query.")


def _llm_judge(query: str, tool_result: str) -> str:
    """LLM-as-judge bonus path. Returns 'success' or 'needs_retry'."""
    llm = get_llm().with_structured_output(_Judgement)
    verdict: _Judgement = llm.invoke(
        [
            (
                "system",
                "You judge whether a tool result satisfactorily resolves a support "
                "query. If the result indicates an error/failure or does not answer "
                "the query, it is NOT satisfactory.",
            ),
            ("human", f"Query: {query}\nTool result: {tool_result}\nIs it satisfactory?"),
        ]
    )
    return "success" if verdict.satisfactory else "needs_retry"


_ANSWER_SYSTEM = """You are a helpful, concise customer-support agent. Write the final \
reply to the customer. Ground your answer ONLY in the provided context (tool results and \
approval decision). Do not invent order numbers, account details, or facts not present in \
the context. Keep it to 1-3 sentences."""


def answer_node(state: AgentState) -> dict:
    """Generate the final response using an LLM grounded in available context."""
    query = state.get("query", "")
    tool_results = state.get("tool_results", []) or []
    approval = state.get("approval")

    context_parts = [f"Customer request: {query}"]
    if tool_results:
        context_parts.append("Tool results:\n- " + "\n- ".join(tool_results))
    if approval:
        context_parts.append(
            f"Approval decision: approved={approval.get('approved')} "
            f"by {approval.get('reviewer')} ({approval.get('comment')})"
        )
    context = "\n\n".join(context_parts)

    started = time.perf_counter()
    llm = get_llm()
    response = llm.invoke([("system", _ANSWER_SYSTEM), ("human", context)])
    answer = response.content if hasattr(response, "content") else str(response)
    latency_ms = int((time.perf_counter() - started) * 1000)

    return {
        "final_answer": answer,
        "messages": ["answer:generated"],
        "events": [
            make_event("answer", "completed", "LLM answer generated", latency_ms=latency_ms)
        ],
    }


def ask_clarification_node(state: AgentState) -> dict:
    """Ask for missing information instead of hallucinating."""
    query = state.get("query", "")
    started = time.perf_counter()
    llm = get_llm()
    response = llm.invoke(
        [
            (
                "system",
                "The customer request is vague or incomplete. Ask ONE specific, polite "
                "clarifying question that would let you act. Do not attempt to answer.",
            ),
            ("human", f"Vague request: {query}"),
        ]
    )
    question = response.content if hasattr(response, "content") else str(response)
    latency_ms = int((time.perf_counter() - started) * 1000)

    return {
        "pending_question": question,
        # A clarification IS the final customer-facing message for this turn.
        "final_answer": question,
        "messages": ["clarify:asked"],
        "events": [
            make_event("clarify", "completed", "clarification requested", latency_ms=latency_ms)
        ],
    }


def risky_action_node(state: AgentState) -> dict:
    """Prepare a risky action for human approval."""
    query = state.get("query", "")
    proposed = (
        f"Proposed high-risk action derived from request: '{query}'. "
        "This has side effects (data mutation / financial / communication) and "
        "requires human approval before execution."
    )
    return {
        "proposed_action": proposed,
        "risk_level": "high",
        "messages": ["risky:proposed"],
        "events": [make_event("risky_action", "completed", "risky action prepared for approval")],
    }


def approval_node(state: AgentState) -> dict:
    """Human-in-the-loop approval step.

    Default: mock approval (approved=True) so tests/CI run offline.
    Extension: set LANGGRAPH_INTERRUPT=true to pause for a real human via interrupt().
    """
    proposed = state.get("proposed_action", "")

    if os.getenv("LANGGRAPH_INTERRUPT", "").lower() == "true":
        from langgraph.types import interrupt

        # Pauses the graph; a human resumes with an ApprovalDecision-shaped payload.
        decision = interrupt(
            {"proposed_action": proposed, "question": "Approve this action?"}
        )
        d = decision if isinstance(decision, dict) else {"approved": bool(decision)}
        approval = {
            "approved": bool(d.get("approved", False)),
            "reviewer": d.get("reviewer", "human"),
            "comment": d.get("comment", ""),
        }
    else:
        approval = {
            "approved": True,
            "reviewer": "mock-reviewer",
            "comment": "auto-approved (mock)",
        }

    return {
        "approval": approval,
        "messages": [f"approval:{approval['approved']}"],
        "events": [
            make_event(
                "approval",
                "completed",
                f"approved={approval['approved']} by {approval['reviewer']}",
                approved=approval["approved"],
            )
        ],
    }


def retry_or_fallback_node(state: AgentState) -> dict:
    """Record a retry attempt: increment the attempt counter and log the failure."""
    attempt = state.get("attempt", 0) + 1
    errors = state.get("errors", []) or []
    last = errors[-1] if errors else "transient failure"
    return {
        "attempt": attempt,
        "errors": [f"retry attempt {attempt}: {last[:80]}"],
        "messages": [f"retry:{attempt}"],
        "events": [make_event("retry", "completed", f"retry attempt {attempt}", attempt=attempt)],
    }


def dead_letter_node(state: AgentState) -> dict:
    """Handle unresolvable failures after max retries are exhausted (layer 3)."""
    attempt = state.get("attempt", 0)
    query = state.get("query", "")
    answer = (
        "We were unable to complete your request automatically after "
        f"{attempt} attempt(s). It has been escalated to a human support agent "
        f"who will follow up. (Original request: {query[:80]})"
    )
    return {
        "final_answer": answer,
        "messages": ["dead_letter:escalated"],
        "events": [
            make_event(
                "dead_letter", "completed", "max retries exhausted; escalated", attempt=attempt
            )
        ],
    }


def finalize_node(state: AgentState) -> dict:
    """Emit a final audit event. All routes pass through here before END."""
    return {
        "messages": ["finalize:done"],
        "events": [make_event("finalize", "completed", "workflow finished")],
    }
