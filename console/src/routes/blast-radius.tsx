import { useEffect, useRef, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import { ArchitectureMap } from "../components/architecture-map";
import {
  architectureHref,
  type InventoryGraphResponse,
} from "../components/architecture-map.model";
import {
  AsyncBoundary,
  DataTable,
  KpiCard,
  KpiGrid,
  PageHeader,
  type AsyncState,
  type Column,
} from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { loadConfig } from "../config";
import { t } from "../i18n";
import { navigate } from "../router";
import {
  BLAST_RADIUS_LINKS,
  blastRadiusHref,
  blastRadiusQueryFromSearch,
  DEFAULT_BLAST_RADIUS_LINKS,
  type BlastRadiusQuery,
} from "./blast-radius.model";

/**
 * Blast-radius simulator panel. Wraps ``GET /simulate/blast-radius`` -
 * the caller supplies a target Resource id + depth + traversal links,
 * the panel renders the reachable subgraph as a table so a reviewer
 * eyeballs "which resources would this action touch" before approving.
 *
 * Purely read-only. There is no button that mutates state; the panel
 * is a projection over the ontology graph the API knows about.
 */

interface ReachedNode {
  readonly resource_id: string;
  readonly depth: number;
  readonly via_link_type: string | null;
}

interface TraversedEdge {
  readonly source: string;
  readonly target: string;
  readonly link_type: string;
  readonly depth: number;
}

interface BlastRadiusResponse {
  readonly target: string;
  readonly traversal_depth: number;
  readonly traversal_links: readonly string[];
  readonly reached: readonly ReachedNode[];
  readonly edges: readonly TraversedEdge[];
  readonly affected_count: number;
  readonly truncated_at_depth: boolean;
}

interface Props {
  readonly client: ReadApiClient;
}

export function BlastRadiusRoute({ client }: Props) {
  const initialQuery = blastRadiusQueryFromSearch(window.location.search);
  const [target, setTarget] = useState(() => initialQuery.target ?? "web-api");
  const [architectureView, setArchitectureView] = useState(initialQuery.architectureView);
  const [depth, setDepth] = useState(initialQuery.depth);
  const [linkSet, setLinkSet] = useState<Set<string>>(() => new Set(initialQuery.links));
  const [state, setState] = useState<AsyncState<BlastRadiusResponse>>({ status: "idle" });
  const requestGeneration = useRef(0);
  const initialSimulationStarted = useRef(false);

  useEffect(() => {
    if (initialSimulationStarted.current) return;
    const config = loadConfig();
    const query = blastRadiusQueryFromSearch(window.location.search);
    const hasExplicitTarget = query.target !== null;
    if (!hasExplicitTarget && !config.devMode && !config.localAzureCliAuth) return;
    initialSimulationStarted.current = true;
    void runSimulation({
      target: query.target ?? target,
      depth: query.depth,
      links: query.links,
      architectureView: query.architectureView,
    });
  }, [client]);

  useEffect(() => {
    const sync = () => {
      requestGeneration.current += 1;
      const query = blastRadiusQueryFromSearch(window.location.search);
      setTarget(query.target ?? "web-api");
      setDepth(query.depth);
      setLinkSet(new Set(query.links));
      setArchitectureView(query.architectureView);
      if (query.target) void runSimulation(query);
      else setState({ status: "idle" });
    };
    window.addEventListener("popstate", sync);
    window.addEventListener("fdai:route-changed", sync);
    return () => {
      window.removeEventListener("popstate", sync);
      window.removeEventListener("fdai:route-changed", sync);
    };
  }, []);

  function toggleLink(name: string): void {
    setLinkSet((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }

  async function runSimulation(query: BlastRadiusQuery = {
    target,
    depth,
    links: [...linkSet],
    architectureView,
  }): Promise<void> {
    if (!query.target) return;
    const generation = requestGeneration.current + 1;
    requestGeneration.current = generation;
    setState({ status: "loading" });
    try {
      const params = new URLSearchParams();
      params.set("target", query.target);
      params.set("depth", String(query.depth));
      for (const link of query.links) params.append("link", link);
      const url = `/simulate/blast-radius?${params.toString()}`;
      const data = await client.panel<BlastRadiusResponse>(url);
      if (requestGeneration.current === generation) setState({ status: "ready", data });
    } catch (err) {
      if (requestGeneration.current === generation) {
        setState({
          status: "error",
          message: err instanceof Error ? err.message : String(err),
        });
      }
    }
  }

  return (
    <div class="stack governance-route blast-radius-route">
      <PageHeader
        title={t("route.blastRadius")}
        subtitle="Simulate the reachable subgraph before approving a change. Read-only projection over the ontology - no resources are touched."
      />

      <section class="stack-section">
        <h3 class="section-title">Query</h3>
        <form
          class="form-grid"
          onSubmit={(e) => {
            e.preventDefault();
            navigate(blastRadiusHref({
              target: target.trim(),
              depth,
              links: [...linkSet],
              architectureView,
            }));
          }}
        >
          <label>
            Target resource id
            <input
              type="text"
              value={target}
              onInput={(e) => setTarget((e.target as HTMLInputElement).value)}
              required
            />
          </label>
          <label>
            Traversal depth (1-5)
            <input
              type="number"
              min={1}
              max={5}
              value={depth}
              onInput={(e) => setDepth(Number((e.target as HTMLInputElement).value))}
              required
            />
          </label>
          <fieldset class="chip-fieldset">
            <legend>Link types</legend>
            <div class="chip-options">
              {BLAST_RADIUS_LINKS.map((name) => (
                <label key={name} class="chip-option">
                  <input
                    type="checkbox"
                    checked={linkSet.has(name)}
                    onChange={() => toggleLink(name)}
                  />
                  <span>{name}</span>
                </label>
              ))}
            </div>
          </fieldset>
          <button
            type="submit"
            class="btn primary"
            disabled={state.status === "loading" || linkSet.size === 0}
          >
            Simulate
          </button>
        </form>
      </section>

      <AsyncBoundary
        state={state}
        resourceLabel="blast-radius simulation"
        idle={<p class="muted footnote">Enter a target and click Simulate.</p>}
      >
        {(data) => <ReportView data={data} client={client} architectureView={architectureView} />}
      </AsyncBoundary>
    </div>
  );
}
function ReportView({ data, client, architectureView }: { readonly data: BlastRadiusResponse; readonly client: ReadApiClient; readonly architectureView: string | null }) {
  const [view, setView] = useState<"impact" | "map" | "table">("impact");
  usePublishViewContext(
    () => ({
      routeId: "blast-radius",
      routeLabel: "Blast radius",
      purpose:
        "Simulates how many resources one action could reach by traversing the " +
        "resource graph from a target. The risk gate caps blast radius so a " +
        "single change can never touch more than its scope. Read-only what-if.",
      glossary: composeGlossary([TERMS.blastRadius, TERMS.actionType]),
      headline: `${data.affected_count} resource(s) reachable at depth ${data.traversal_depth}${data.truncated_at_depth ? " (truncated)" : ""}`,
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "target", value: data.target, group: "query" },
        { key: "depth", value: data.traversal_depth, group: "query" },
        { key: "links", value: data.traversal_links.join(", ") || "(none)", group: "query" },
        { key: "affected_count", value: data.affected_count, group: "result" },
        { key: "edge_count", value: data.edges.length, group: "result" },
        { key: "truncated", value: data.truncated_at_depth, group: "result" },
      ],
      records: {
        reached: data.reached.map((n) => ({
          resource_id: n.resource_id,
          depth: n.depth,
          via_link_type: n.via_link_type,
        })),
        edges: data.edges.map((e) => ({
          source: e.source,
          target: e.target,
          link_type: e.link_type,
          depth: e.depth,
        })),
      },
    }),
    [data],
  );

  const reachedColumns: readonly Column<ReachedNode>[] = [
    { key: "d", header: "Depth", render: (n) => n.depth, cellClass: "num", headerClass: "num" },
    {
      key: "id",
      header: "Resource id",
      render: (n) => <a href={architectureHref(n.resource_id, architectureView)}>{n.resource_id}</a>,
      cellClass: "mono",
    },
    {
      key: "via",
      header: "Reached via",
      render: (n) => n.via_link_type ?? <span class="muted">(target)</span>,
      cellClass: "mono",
    },
  ];
  const edgeColumns: readonly Column<TraversedEdge>[] = [
    { key: "d", header: "Depth", render: (e) => e.depth, cellClass: "num", headerClass: "num" },
    {
      key: "s",
      header: "Source",
      render: (e) => <a href={architectureHref(e.source, architectureView)}>{e.source}</a>,
      cellClass: "mono",
    },
    { key: "l", header: "Link", render: (e) => e.link_type, cellClass: "mono" },
    {
      key: "t",
      header: "Target",
      render: (e) => <a href={architectureHref(e.target, architectureView)}>{e.target}</a>,
      cellClass: "mono",
    },
  ];

  return (
    <div class="stack">
      <div class="governance-summary-strip" aria-label="Blast-radius context">
        <span class="is-steel"><strong>{data.target}</strong></span>
        <span>depth {data.traversal_depth}</span>
        <span>{data.traversal_links.join(" + ") || "no links"}</span>
        <span class={data.truncated_at_depth ? "is-plum" : "is-teal"}>
          {data.truncated_at_depth ? "truncated at depth cap" : "bounded neighborhood complete"}
        </span>
      </div>
      <KpiGrid>
        <KpiCard
          label="Affected resources"
          value={data.affected_count}
          tone={data.affected_count > 25 ? "warning" : "default"}
        />
        <KpiCard label="Traversal depth" value={data.traversal_depth} />
        <KpiCard
          label="Truncated at cap"
          value={data.truncated_at_depth ? "yes" : "no"}
          tone={data.truncated_at_depth ? "warning" : "positive"}
          hint={data.truncated_at_depth ? "raise --depth to see more" : "full graph explored"}
        />
      </KpiGrid>

      <section class="stack-section">
        <div class="section-header">
          <h3 class="section-title">Affected topology</h3>
          <div class="segmented-control" role="group" aria-label="Blast radius view">
            <button type="button" class={view === "impact" ? "active" : ""} onClick={() => setView("impact")}>Impact</button>
            <button type="button" class={view === "map" ? "active" : ""} onClick={() => setView("map")}>Map</button>
            <button type="button" class={view === "table" ? "active" : ""} onClick={() => setView("table")}>Table</button>
          </div>
        </div>
        {view === "impact" ? (
          <BlastImpact data={data} />
        ) : view === "map" ? (
          <BlastRadiusMap client={client} data={data} architectureView={architectureView} />
        ) : (
          <DataTable
            columns={reachedColumns}
            rows={data.reached}
            keyOf={(node) => `${node.depth}:${node.resource_id}`}
            empty="No reachable resources at this depth."
          />
        )}
      </section>

      <section class="stack-section">
        <h3 class="section-title">Edges traversed ({data.edges.length})</h3>
        <DataTable
          columns={edgeColumns}
          rows={data.edges}
          keyOf={(_e, i) => `${i}`}
          empty="No edges walked."
        />
      </section>
    </div>
  );
}
function BlastImpact({ data }: { readonly data: BlastRadiusResponse }) {
  const nodes = data.reached.filter((node) => node.resource_id !== data.target);
  const maxDepth = Math.max(1, data.traversal_depth);
  return (
    <div class="blast-impact-layout">
      <div class="blast-rings" role="img" aria-label={`Blast radius around ${data.target}`}>
        <svg viewBox="0 0 560 430">
          {Array.from({ length: maxDepth }, (_, index) => {
            const depth = maxDepth - index;
            const radius = 58 + depth * 58;
            return <circle key={depth} cx="280" cy="215" r={radius} class={`blast-ring depth-${depth}`} />;
          })}
          <circle cx="280" cy="215" r="42" class="blast-target" />
          <text x="280" y="211" text-anchor="middle" class="blast-target-label">target</text>
          <text x="280" y="229" text-anchor="middle" class="blast-target-name">{shortResource(data.target)}</text>
          {nodes.slice(0, 24).map((node, index) => {
            const peers = nodes.filter((candidate) => candidate.depth === node.depth);
            const peerIndex = peers.indexOf(node);
            const angle = (Math.PI * 2 * peerIndex) / Math.max(1, peers.length) - Math.PI / 2;
            const radius = 58 + Math.max(1, node.depth) * 58;
            const x = 280 + Math.cos(angle) * radius;
            const y = 215 + Math.sin(angle) * radius;
            return (
              <g key={`${node.resource_id}:${index}`}>
                <circle cx={x} cy={y} r="8" class={`blast-node depth-${node.depth}`} />
                <text x={x} y={y + 20} text-anchor="middle" class="blast-node-label">{shortResource(node.resource_id)}</text>
              </g>
            );
          })}
        </svg>
      </div>
      <section class="blast-impact-list">
        <header>
          <h4>Impact tree</h4>
          <span>{data.affected_count} affected</span>
        </header>
        <ol>
          <li class="is-target"><span>0</span><a href={architectureHref(data.target)}><code>{data.target}</code></a><small>target</small></li>
          {data.reached.map((node) => (
            <li key={`${node.depth}:${node.resource_id}`}>
              <span>{node.depth}</span>
              <a href={architectureHref(node.resource_id)}><code>{node.resource_id}</code></a>
              <small>{node.via_link_type ?? "direct"}</small>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
function shortResource(value: string): string {
  const parts = value.split("/").filter(Boolean);
  const last = parts[parts.length - 1] ?? value;
  return last.length > 22 ? `${last.slice(0, 20)}...` : last;
}

function BlastRadiusMap({ client, data, architectureView }: { readonly client: ReadApiClient; readonly data: BlastRadiusResponse; readonly architectureView: string | null }) {
  const [graph, setGraph] = useState<InventoryGraphResponse | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    const params: Record<string, string> = {
      depth: "4",
      include: "contains,attached_to,depends_on",
    };
    if (architectureView) params.scope = architectureView;
    client.panel<InventoryGraphResponse>("/inventory/graph", params).then(
      (value) => { if (!cancelled) setGraph(value); },
      (error: unknown) => { if (!cancelled) setMessage(error instanceof Error ? error.message : String(error)); },
    );
    return () => { cancelled = true; };
  }, [client, architectureView]);
  if (message) return <p class="muted footnote">Map unavailable: {message}</p>;
  if (!graph) return <p class="muted footnote">Loading architecture map...</p>;
  const highlighted = new Set([data.target, ...data.reached.map((node) => node.resource_id)]);
  return (
    <div class="blast-map-wrap">
      <ArchitectureMap graph={graph} highlightedIds={highlighted} selectedId={data.target} />
      <a class="btn blast-map-open" href={architectureHref(data.target, architectureView)}>Open full architecture</a>
    </div>
  );
}
