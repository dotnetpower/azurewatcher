/**
 * Now > Agents route (Track B, Phase 2).
 *
 * An agent-centric, read-only view of the pantheon: all 15 agents as a
 * constellation with a live status ring, that lights up the involved
 * agents when an incident (e.g. a chaos experiment) fires and renders the
 * collaboration (detect -> ticket -> RCA conversation -> resolve) as it
 * streams over `GET /agents/stream`.
 *
 * Pure read-only: no privileged calls. The SSE consumer
 * ({@link useAgentStream}) is a translator, never a judge.
 */

import { useEffect, useLayoutEffect, useMemo, useReducer, useRef, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import { loadConfig } from "../config";
import { useAgentStream } from "../hooks/use-agent-stream";
import { usePublishViewContext } from "../deck/context";
import { agentTerm, composeGlossary, TERMS } from "../deck/glossary";
import { openDeckWithPrompt } from "../deck/open-deck";
import {
  PANTHEON,
  activeAgentCount,
  engagedGroups,
  isEngaged,
  makeInitialState,
  reducer,
  STATE_TASK,
  type AgentNode,
  type EngagedGroup,
  type Incident,
} from "./agents.model";

interface Props {
  readonly client: ReadApiClient;
}

const _STATE_LABEL: Record<string, string> = {
  idle: "idle",
  watching: "watching",
  collecting: "collecting",
  analyzing: "analyzing",
  deciding: "deciding",
  executing: "executing",
  approving: "approving",
  auditing: "auditing",
};

/** A node's measured centre within the constellation, in local px. */
interface Point {
  readonly x: number;
  readonly y: number;
}

interface Geometry {
  readonly centers: Record<string, Point>;
  readonly w: number;
  readonly h: number;
}

const EMPTY_GEOMETRY: Geometry = { centers: {}, w: 0, h: 0 };

/** How many incidents the side list shows before the "All" toggle. */
const INCIDENT_PREVIEW = 10;

/** Stable hue (0-360) for an incident so its links + label share a colour. */
function hueForIncident(correlationId: string): number {
  let h = 0;
  for (let i = 0; i < correlationId.length; i++) {
    h = (h * 31 + correlationId.charCodeAt(i)) % 360;
  }
  return h;
}

/** All unordered pairs of a list - the mesh of links inside one incident. */
function pairsOf(names: readonly string[]): [string, string][] {
  const out: [string, string][] = [];
  for (let i = 0; i < names.length; i++) {
    for (let j = i + 1; j < names.length; j++) {
      out.push([names[i]!, names[j]!]);
    }
  }
  return out;
}

/** Centroid of the measured points, used to anchor the ticket label. */
function centroid(points: readonly Point[]): Point | null {
  if (points.length === 0) return null;
  const sum = points.reduce((acc, p) => ({ x: acc.x + p.x, y: acc.y + p.y }), { x: 0, y: 0 });
  return { x: sum.x / points.length, y: sum.y / points.length };
}

export function AgentsRoute({ client: _client }: Props) {
  const [state, dispatch] = useReducer(reducer, undefined, makeInitialState);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const url = useMemo(() => {
    const cfg = loadConfig();
    const base =
      cfg.readApiBaseUrl || (typeof window !== "undefined" ? window.location.origin : "");
    return `${base.replace(/\/$/, "")}/agents/stream`;
  }, []);

  const { status } = useAgentStream({
    url,
    onEvent: (msg) => dispatch({ kind: "message", msg }),
  });

  // Auto-follow the newest incident until the operator picks one.
  const [pinned, setPinned] = useState(false);
  useEffect(() => {
    if (!pinned && state.incidentOrder.length > 0) {
      const first = state.incidentOrder[0];
      if (first) setSelectedId(first);
    }
  }, [state.incidentOrder, pinned]);

  // Incident list shows the most recent `INCIDENT_PREVIEW` (newest first);
  // the "All" toggle expands to the full retained history.
  const [showAllIncidents, setShowAllIncidents] = useState(false);

  const selected: Incident | null = selectedId ? (state.incidents[selectedId] ?? null) : null;
  const involved = useMemo(
    () => new Set(selected?.involved ?? []),
    [selected],
  );

  const active = activeAgentCount(state);

  // Agents currently co-engaged, grouped by the incident they work on.
  // Drives the connection lines: one group == one ticket == one link mesh.
  const groups = useMemo(() => engagedGroups(state), [state.agents, state.incidents]);

  // Which agent the pointer is over - emphasises its links and shows the
  // hover card. Kept in state (not just CSS) so the SVG links react too.
  const [hoveredAgent, setHoveredAgent] = useState<string | null>(null);

  // Measured node centres so the SVG overlay can draw links between the
  // real rendered positions of the constellation grid. Re-measured after
  // every layout change and on resize (ResizeObserver), so the lines track
  // reflow without hard-coding a layout.
  const constellationRef = useRef<HTMLDivElement | null>(null);
  const nodeRefs = useRef(new Map<string, HTMLDivElement>());
  const [geometry, setGeometry] = useState<Geometry>(EMPTY_GEOMETRY);

  useLayoutEffect(() => {
    const container = constellationRef.current;
    if (!container || typeof ResizeObserver === "undefined") return undefined;
    const measure = (): void => {
      const box = container.getBoundingClientRect();
      const centers: Record<string, Point> = {};
      for (const [name, el] of nodeRefs.current) {
        const ring = (el.querySelector(".agent-ring") as HTMLElement | null) ?? el;
        const r = ring.getBoundingClientRect();
        centers[name] = {
          x: r.left - box.left + r.width / 2,
          y: r.top - box.top + r.height / 2,
        };
      }
      setGeometry({ centers, w: box.width, h: box.height });
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(container);
    return () => ro.disconnect();
    // Re-measure whenever the set of agent nodes changes (a state message
    // rebuilds `state.agents`), because engagement can reflow node sizes.
  }, [state.agents]);

  usePublishViewContext(
    () => ({
      routeId: "agents",
      routeLabel: "Agents",
      purpose:
        "The 15-agent pantheon, live. Each incident (correlation id) is one " +
        "collaboration: Huginn/Heimdall sense, Forseti judges, Var queues a HIL " +
        "approval, Thor executes, Saga records. Read-only - ask the deck about " +
        "the selected incident, or propose a runtime action (it is judged, never " +
        "executed from here).",
      glossary: composeGlossary([
        TERMS.correlationId,
        TERMS.hil,
        TERMS.outcome,
        TERMS.gateDecision,
        agentTerm(),
      ]),
      headline: selected
        ? `${selected.title} (${selected.status}) - ${selected.involved.length} agent(s), ${selected.turns.length} turn(s)`
        : `${state.incidentOrder.length} incident(s) - ${active} agent(s) engaged`,
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "incidents", value: state.incidentOrder.length, group: "page" },
        { key: "engaged", value: active, group: "page" },
        { key: "selected", value: selected?.ticketId ?? "-", group: "incident" },
        { key: "status", value: selected?.status ?? "-", group: "incident" },
        { key: "severity", value: selected?.severity ?? "-", group: "incident" },
      ],
      records: {
        // The selected incident's agent-to-agent conversation so the deck can
        // answer "what's the root cause / who's involved / what did they say"
        // grounded in the live thread. Empty when nothing is selected.
        conversation: (selected?.turns ?? []).slice(-40).map((t) => ({
          from_agent: t.from_agent,
          to_agent: t.to_agent,
          kind: t.kind,
          text: t.text,
          at: t.ts,
        })),
        incidents: state.incidentOrder.map((id) => {
          const inc = state.incidents[id];
          return {
            ticket: inc?.ticketId ?? id,
            title: inc?.title ?? "-",
            status: inc?.status ?? "-",
            severity: inc?.severity ?? "-",
            correlation_id: id,
          };
        }),
      },
    }),
    [state, selected, active],
  );

  return (
    <div class="agents-route">
      <header class="agents-head">
        <div>
          <h2>Agents</h2>
          <p class="agents-sub">
            The 15-agent pantheon, live. Connection lines tie the agents
            working the same ticket together; hover an agent to see what it is
            doing right now. Wire: <code>GET /agents/stream</code>.
          </p>
        </div>
        <div class="agents-meta">
          <span class={`agents-conn conn-${status}`}>{status}</span>
          <span class="agents-active">
            <strong>{active}</strong> engaged
          </span>
        </div>
      </header>

      <div class="agents-layout">
        <section
          class="agents-constellation"
          aria-label="agent constellation"
          ref={constellationRef}
        >
          <ConstellationLinks
            groups={groups}
            geometry={geometry}
            selectedId={selectedId}
            hoveredAgent={hoveredAgent}
          />
          {PANTHEON.map(({ name }) => {
            const node = state.agents[name];
            if (!node) return null;
            const isInvolved = involved.has(name);
            const dim = selected !== null && !isInvolved;
            const engaged = isEngaged(node);
            const incident = node.correlationId
              ? (state.incidents[node.correlationId] ?? null)
              : null;
            return (
              <div
                key={name}
                ref={(el) => {
                  if (el) nodeRefs.current.set(name, el as HTMLDivElement);
                  else nodeRefs.current.delete(name);
                }}
                class={`agent-node layer-${node.layer} state-${node.state}${
                  isInvolved ? " is-involved" : ""
                }${dim ? " is-dim" : ""}${engaged ? " is-engaged" : ""}${
                  hoveredAgent === name ? " is-hovered" : ""
                }`}
                onMouseEnter={() => setHoveredAgent(name)}
                onMouseLeave={() =>
                  setHoveredAgent((cur) => (cur === name ? null : cur))
                }
              >
                <span class="agent-ring" aria-hidden="true" />
                <span class="agent-name">{name}</span>
                <span class="agent-state">{_STATE_LABEL[node.state] ?? node.state}</span>
                <AgentHoverCard node={node} incident={incident} />
              </div>
            );
          })}
        </section>

        <aside class="agents-side">
          <div class="agents-incident-list" aria-label="incidents">
            <div class="agents-incident-head">
              <h3>Incidents</h3>
              {state.incidentOrder.length > INCIDENT_PREVIEW && (
                <button
                  type="button"
                  class={`agents-incident-all${showAllIncidents ? " is-active" : ""}`}
                  aria-pressed={showAllIncidents}
                  onClick={() => setShowAllIncidents((v) => !v)}
                >
                  {showAllIncidents ? "Recent" : `All (${state.incidentOrder.length})`}
                </button>
              )}
            </div>
            {state.incidentOrder.length === 0 ? (
              <p class="agents-empty">No incidents - autonomy holding.</p>
            ) : (
              <ul>
                {(showAllIncidents
                  ? state.incidentOrder
                  : state.incidentOrder.slice(0, INCIDENT_PREVIEW)
                ).map((id) => {
                  const inc = state.incidents[id];
                  if (!inc) return null;
                  return (
                    <li key={id}>
                      <button
                        type="button"
                        class={`incident-row sev-${inc.severity} status-${inc.status}${
                          id === selectedId ? " is-selected" : ""
                        }`}
                        onClick={() => {
                          setSelectedId(id);
                          setPinned(true);
                        }}
                      >
                        <span class="incident-status">{inc.status}</span>
                        <span class="incident-title">{inc.title}</span>
                        <span class="incident-ticket">{inc.ticketId}</span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          <IncidentWorkflow incident={selected} />
        </aside>
      </div>
    </div>
  );
}

/**
 * SVG overlay that draws a connection-line mesh between every pair of
 * agents co-engaged on the same incident, so the operator can see which
 * ticket each agent is working on and with whom. One colour per incident;
 * the selected incident (or the hovered agent's links) is emphasised while
 * the rest fade back. Purely decorative - `pointer-events: none` so the
 * nodes underneath stay interactive; `aria-hidden` because the same
 * information is available as text in the incident list + hover card.
 */
function ConstellationLinks({
  groups,
  geometry,
  selectedId,
  hoveredAgent,
}: {
  readonly groups: readonly EngagedGroup[];
  readonly geometry: Geometry;
  readonly selectedId: string | null;
  readonly hoveredAgent: string | null;
}) {
  if (geometry.w === 0 || groups.length === 0) return null;
  const { centers } = geometry;
  const anySelected = selectedId !== null;

  return (
    <svg
      class="agents-links"
      width={geometry.w}
      height={geometry.h}
      viewBox={`0 0 ${geometry.w} ${geometry.h}`}
      aria-hidden="true"
    >
      {groups.map((g) => {
        const hue = hueForIncident(g.correlationId);
        const stroke = `hsl(${hue} 80% 62%)`;
        const isSelected = g.correlationId === selectedId;
        const measured = g.agents.map((n) => centers[n]).filter((p): p is Point => Boolean(p));
        const mid = centroid(measured);
        return (
          <g key={g.correlationId}>
            {pairsOf(g.agents).map(([a, b]) => {
              const ca = centers[a];
              const cb = centers[b];
              if (!ca || !cb) return null;
              const touchesHover =
                hoveredAgent !== null && (a === hoveredAgent || b === hoveredAgent);
              const emphasis = isSelected || touchesHover;
              const opacity = anySelected && !emphasis ? 0.1 : emphasis ? 0.7 : 0.32;
              return (
                <line
                  key={`${a}-${b}`}
                  class={`agent-link${emphasis ? " is-emphasis" : ""}`}
                  x1={ca.x}
                  y1={ca.y}
                  x2={cb.x}
                  y2={cb.y}
                  stroke={stroke}
                  stroke-width={emphasis ? 2 : 1.2}
                  stroke-opacity={opacity}
                />
              );
            })}
            {mid && g.incident && (
              <text
                class={`agent-link-label${isSelected ? " is-emphasis" : ""}`}
                x={mid.x}
                y={mid.y}
                fill={stroke}
                fill-opacity={anySelected && !isSelected ? 0.35 : 0.9}
                text-anchor="middle"
              >
                {g.incident.ticketId || "incident"}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

/**
 * Hover card revealed when the pointer is over an agent node. Answers the
 * operator's "what is this agent doing right now?" - it shows the coarse
 * state, a plain-language task description, the streamed `detail` when
 * present, and the incident (ticket + title) the agent is engaged on.
 */
function AgentHoverCard({
  node,
  incident,
}: {
  readonly node: AgentNode;
  readonly incident: Incident | null;
}) {
  const task = STATE_TASK[node.state] ?? node.state;
  return (
    <div class="agent-tooltip" role="tooltip">
      <div class="agent-tooltip-head">
        <strong>{node.name}</strong>
        <span class={`agent-tooltip-state state-${node.state}`}>
          {_STATE_LABEL[node.state] ?? node.state}
        </span>
      </div>
      <p class="agent-tooltip-task">{task}</p>
      {node.detail && <p class="agent-tooltip-detail">{node.detail}</p>}
      {incident ? (
        <div class="agent-tooltip-incident">
          <span class="agent-tooltip-ticket">{incident.ticketId || "incident"}</span>
          <span class="agent-tooltip-title">{incident.title}</span>
        </div>
      ) : (
        <p class="agent-tooltip-idle">Not engaged on any incident.</p>
      )}
    </div>
  );
}

function IncidentWorkflow({ incident }: { incident: Incident | null }) {
  if (incident === null) {
    return (
      <div class="incident-workflow is-empty">
        <p>Select an incident to watch the agents collaborate.</p>
      </div>
    );
  }
  const steps: { readonly key: string; readonly label: string; readonly done: boolean }[] = [
    { key: "detect", label: "Detect", done: true },
    { key: "ticket", label: "Ticket", done: incident.ticketId !== "" },
    {
      key: "rca",
      label: "RCA",
      done: incident.status === "investigating" || incident.status === "resolved",
    },
    { key: "resolve", label: "Resolve", done: incident.status === "resolved" },
  ];
  return (
    <div class="incident-workflow">
      <div class="incident-workflow-head">
        <span class={`incident-status status-${incident.status}`}>{incident.status}</span>
        <span class="incident-workflow-title">{incident.title}</span>
        <span class="incident-ticket">{incident.ticketId}</span>
      </div>

      <div class="incident-deck-actions">
        <button
          type="button"
          class="incident-ask-deck"
          onClick={() =>
            openDeckWithPrompt(
              `About incident ${incident.ticketId} (${incident.correlationId}): what is the root cause and what are the agents doing?`,
            )
          }
        >
          Ask the deck about this incident
        </button>
        <span class="incident-deck-hint">
          Questions are read-only; a command opens a proposal (judged, never
          executed here).
        </span>
      </div>

      <ol class="incident-steps">
        {steps.map((s) => (
          <li key={s.key} class={s.done ? "step-done" : "step-pending"}>
            {s.label}
          </li>
        ))}
      </ol>

      <div class="incident-conversation" aria-label="agent conversation">
        {incident.turns.length === 0 ? (
          <p class="agents-empty">No conversation yet.</p>
        ) : (
          incident.turns.map((t, i) => (
            <div key={i} class={`turn kind-${t.kind}`}>
              <span class="turn-from">{t.from_agent}</span>
              <span class="turn-arrow" aria-hidden="true">
                {"->"}
              </span>
              <span class="turn-to">{t.to_agent}</span>
              <span class="turn-text">{t.text}</span>
            </div>
          ))
        )}
      </div>

      {incident.rca !== null && (
        <div class="incident-rca">
          <span class="incident-rca-label">Root cause</span>
          <p>{incident.rca}</p>
        </div>
      )}
    </div>
  );
}
