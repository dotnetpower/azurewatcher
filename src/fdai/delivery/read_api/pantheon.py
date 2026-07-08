"""Read-only pantheon graph and workflows routes.

Two endpoints:

- ``GET /pantheon/graph`` - the 15 agents + their org chart edges + owned
  object types + subscribed / published topics + LLM hot-path flag.
- ``GET /pantheon/workflows`` - the 10 cross-agent workflows with
  primary agent, participants, trigger, promotion gate.

Both routes are pure projections of the in-memory pantheon registry
(``fdai.agents``). They add no state, register no side effects, and
require the Reader role. Opt-in through
:class:`~fdai.delivery.read_api.main.ReadApiConfig` (empty by default).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai.agents import PANTHEON_SPECS
from fdai.agents.base import AgentSpec
from fdai.agents.workflows import WORKFLOWS, WorkflowSpec

GRAPH_ROUTE_PATH = "/pantheon/graph"
WORKFLOWS_ROUTE_PATH = "/pantheon/workflows"


def _serialize_agent(spec: AgentSpec) -> dict[str, object]:
    return {
        "name": spec.name,
        "layer": spec.layer.value,
        "reports_to": spec.reports_to,
        "owns": list(spec.owns),
        "executes": list(spec.executes),
        "initiates": list(spec.initiates),
        "subscribes": list(spec.subscribes),
        "publishes": list(spec.publishes),
        "question_domains": list(spec.question_domains),
        "owns_code_paths": list(spec.owns_code_paths),
        "hot_path_llm": spec.hot_path_llm,
        "off_path_llm": spec.off_path_llm,
        "hard_dependency": spec.hard_dependency,
        "rate_limits": {
            "per_minute": spec.rate_limits.per_minute,
            "per_hour": spec.rate_limits.per_hour,
        },
    }


def _serialize_workflow(w: WorkflowSpec) -> dict[str, object]:
    return {
        "id": w.id,
        "name": w.name,
        "primary_agent": w.primary_agent,
        "participating_agents": list(w.participating_agents),
        "trigger": w.trigger,
        "default_mode": w.default_mode,
        "promotion_gate": w.promotion_gate,
    }


def make_pantheon_graph_route(
    *,
    authorize: Callable[[Request], Awaitable[str]],
    path: str = GRAPH_ROUTE_PATH,
) -> Route:
    """Return the ``GET /pantheon/graph`` route."""

    async def handler(request: Request) -> Response:
        await authorize(request)
        agents = [_serialize_agent(s) for s in PANTHEON_SPECS]
        # Derived org-chart edges (reports_to relationships).
        edges = [
            {"from": s.reports_to, "to": s.name} for s in PANTHEON_SPECS if s.reports_to is not None
        ]
        return JSONResponse(
            {
                "agents": agents,
                "org_edges": edges,
                "agent_count": len(agents),
                "hard_dependency_agents": sorted(
                    s.name for s in PANTHEON_SPECS if s.hard_dependency
                ),
                "hot_path_llm_agents": sorted(s.name for s in PANTHEON_SPECS if s.hot_path_llm),
                "mermaid": _render_org_chart_mermaid(),
            }
        )

    return Route(path, handler, methods=["GET"])


def _render_org_chart_mermaid() -> str:
    """Render the pantheon org chart as a deterministic Mermaid ``graph TD``.

    Format matches the diagrams in
    ``docs/roadmap/agent-pantheon.md`` \u00a72 so a fork's org-chart edit
    surfaces a diffable change in the exported markdown.
    """
    lines: list[str] = ["graph TD"]
    for spec in PANTHEON_SPECS:
        label = f"{spec.name}<br/>({spec.layer.value})"
        lines.append(f'    {spec.name}["{label}"]')
    for spec in PANTHEON_SPECS:
        if spec.reports_to is not None:
            arrow = "-.->" if spec.layer.value == "governance" else "-->"
            lines.append(f"    {spec.reports_to} {arrow} {spec.name}")
    return "\n".join(lines)


def make_pantheon_workflows_route(
    *,
    authorize: Callable[[Request], Awaitable[str]],
    path: str = WORKFLOWS_ROUTE_PATH,
) -> Route:
    """Return the ``GET /pantheon/workflows`` route."""

    async def handler(request: Request) -> Response:
        await authorize(request)
        return JSONResponse(
            {
                "workflows": [_serialize_workflow(w) for w in WORKFLOWS],
                "count": len(WORKFLOWS),
            }
        )

    return Route(path, handler, methods=["GET"])


__all__ = [
    "GRAPH_ROUTE_PATH",
    "WORKFLOWS_ROUTE_PATH",
    "make_pantheon_graph_route",
    "make_pantheon_workflows_route",
]
