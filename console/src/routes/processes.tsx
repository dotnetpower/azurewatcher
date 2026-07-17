import { useEffect, useReducer, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import { AsyncBoundary, EmptyState, PageHeader, StatusPill, type AsyncState } from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { t } from "../i18n";
import { currentRoute, routeHref } from "../router";
import { ProcessWidget, RenderedRegion } from "./process-view-renderer";
import { schedulerRunsText } from "./scheduler-runs.i18n";
import { SchedulerRunsRoute } from "./scheduler-runs";
import {
  decodeProcessList,
  decodeProcessJournal,
  decodeRenderedProcessView,
    displayValue,
    INITIAL_PROCESS_REFRESH,
    type ProcessDetailData,
    type ProcessEvent,
  defaultProcessId,
  processHref,
  processEventHref,
  processIdFromHash,
  processListFailure,
  processTone,
  reduceProcessRefresh,
  type ProcessListResponse,
  type ProcessSummary,
  type RenderedProcessView,
} from "./processes.model";

interface Props { readonly client: ReadApiClient }

interface LoadedProcessList {
  readonly response: ProcessListResponse;
  readonly generation: number;
}

export function ProcessesRoute({ client }: Props) {
  if (currentRoute().segments[0] === "scheduler-runs") {
    return <SchedulerRunsRoute client={client} />;
  }
  return <ProcessRuntimeRoute client={client} />;
}

function ProcessRuntimeRoute({ client }: Props) {
  const [listState, setListState] = useState<AsyncState<LoadedProcessList>>({ status: "loading" });
  const [selectedId, setSelectedId] = useState<string | null>(() => currentRoute().segments[0] ?? null);
  const [detailState, setDetailState] = useState<AsyncState<ProcessDetailData>>({ status: "idle" });
  const [refreshCycle, dispatchRefresh] = useReducer(reduceProcessRefresh, INITIAL_PROCESS_REFRESH);

  useEffect(() => {
    const sync = () => setSelectedId(currentRoute().segments[0] ?? null);
    window.addEventListener("popstate", sync);
    window.addEventListener("fdai:route-changed", sync);
    return () => {
      window.removeEventListener("popstate", sync);
      window.removeEventListener("fdai:route-changed", sync);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    client.panel<unknown>("/views/process").then(
      (payload) => {
        if (cancelled) return;
        let data: ProcessListResponse;
        try {
          data = decodeProcessList(payload);
        } catch (error) {
          setListState(processListFailure(error));
          dispatchRefresh({ type: "finish", generation: refreshCycle.generation });
          return;
        }
        setListState({
          status: "ready",
          data: { response: data, generation: refreshCycle.generation },
        });
        const defaultId = currentRoute().segments[0] ?? defaultProcessId(data.items, "");
        if (!currentRoute().segments[0] && defaultId) {
          window.history.replaceState(window.history.state, "", processHref(defaultId));
          setSelectedId(defaultId);
        } else if (!defaultId) {
          dispatchRefresh({ type: "finish", generation: refreshCycle.generation });
        }
      },
      (error: unknown) => {
        if (cancelled) return;
        setListState(processListFailure(error));
        dispatchRefresh({ type: "finish", generation: refreshCycle.generation });
      },
    );
    return () => { cancelled = true; };
  }, [client, refreshCycle.generation]);

  useEffect(() => {
    if (listState.status !== "ready") return;
    const generation = listState.data.generation;
    if (!selectedId) {
      setDetailState({ status: "idle" });
      dispatchRefresh({ type: "finish", generation });
      return;
    }
    let cancelled = false;
    setDetailState({ status: "loading" });
    const encodedId = encodeURIComponent(selectedId);
    void (async () => {
      try {
        const journalPayload = await client.panel<unknown>(`/views/process/${encodedId}/events`);
        const journal = decodeProcessJournal(journalPayload);
        const viewPayload = journal.process.has_view
          ? await client.panel<unknown>(`/views/process/${encodedId}`)
          : null;
        if (!cancelled) {
          setDetailState({
            status: "ready",
            data: {
              journal,
              view: viewPayload === null ? null : decodeRenderedProcessView(viewPayload),
            },
          });
        }
      } catch (error) {
        if (!cancelled) {
          setDetailState({ status: "error", message: error instanceof Error ? error.message : String(error) });
        }
      } finally {
        if (!cancelled) dispatchRefresh({ type: "finish", generation });
      }
    })();
    return () => { cancelled = true; };
  }, [client, selectedId, listState]);

  return (
    <div class="stack process-route">
      <PageHeader
        title={t("route.processes")}
        subtitle="Workflow run status from authoritative Process snapshots and append-only journals. Execution remains outside the console."
        actions={
          <>
            <a class="btn btn-small" href={routeHref("processes", { segments: ["scheduler-runs"] })}>
              {schedulerRunsText("title")}
            </a>
            <button
              type="button"
              class="btn btn-small"
              disabled={refreshCycle.refreshing || listState.status === "loading" || detailState.status === "loading"}
              aria-busy={refreshCycle.refreshing}
              onClick={() => dispatchRefresh({ type: "start" })}
            >
              {refreshCycle.refreshing ? "Refreshing..." : "Refresh status"}
            </button>
          </>
        }
      />
      <AsyncBoundary state={listState} resourceLabel="processes">
        {(data) => <ProcessWorkspace processList={data.response} selectedId={selectedId} detailState={detailState} />}
      </AsyncBoundary>
    </div>
  );
}

function ProcessWorkspace({ processList, selectedId, detailState }: {
  readonly processList: ProcessListResponse;
  readonly selectedId: string | null;
  readonly detailState: AsyncState<ProcessDetailData>;
}) {
  const processes = processList.items;
  const selected = processes.find((item) => item.id === selectedId) ?? null;
  usePublishViewContext(
    () => ({
      routeId: "processes",
      routeLabel: "Processes",
      purpose: "Read-only workflow Process snapshots and ontology-backed dynamic views.",
      glossary: composeGlossary([TERMS.process, TERMS.viewSpec]),
      headline: `${processes.length} process(es)${selected ? ` - ${selected.workflow_ref}: ${selected.status}` : ""}`,
      capturedAt: selected?.updated_at ?? new Date().toISOString(),
      facts: [
        { key: "process_count", value: processes.length, group: "process" },
        { key: "source", value: processList.source, group: "process" },
        { key: "synthetic", value: processList.synthetic, group: "process" },
        { key: "durable", value: processList.durable, group: "process" },
        { key: "selected", value: selected?.id ?? "-", group: "process" },
        { key: "status", value: selected?.status ?? "-", group: "process" },
      ],
      records: {
        processes: processes.map((process) => ({
          id: process.id,
          workflow_ref: process.workflow_ref,
          workflow_version: process.workflow_version,
          status: process.status,
          current_step: process.current_step,
          target_resource_id: process.target_resource_id,
          updated_at: process.updated_at,
          has_view: process.has_view,
        })),
      },
    }),
    [processList, processes, selected],
  );
  if (processes.length === 0) {
    return <EmptyState title="No workflow processes" body="Process runs appear here after the workflow runtime records them." />;
  }
  const hasRenderableProcess = processes.some((process) => process.has_view);
  return (
    <div class="stack process-status-workspace">
      <div class="filter-summary" aria-label="Process projection provenance">
        <span>Source: <strong>{processList.source}</strong></span>
        <span>Evidence: <strong>
          {processList.synthetic === true ? "Synthetic" : processList.synthetic === false ? "Observed" : "Unknown"}
        </strong></span>
        <span>Storage: <strong>
          {processList.durable === true ? "Durable" : processList.durable === false ? "Volatile" : "Unknown"}
        </strong></span>
      </div>
      <ProcessStatusSummary processes={processes} />
      <div class="process-workspace">
        <aside class="process-list" aria-label="Workflow processes">
          {processes.map((process) => (
          <a key={process.id} href={processHref(process.id)} class={`process-list-entry ${process.id === selectedId ? "is-active" : ""}`}>
            <ProcessListLabel process={process} />
          </a>
          ))}
        </aside>
        <section class="process-view-stage">
          <AsyncBoundary state={detailState} resourceLabel="process status" idle={<p class="muted">{hasRenderableProcess ? "Select a process." : "Select a process to inspect its runtime journal."}</p>}>
            {(detail) => <ProcessDetail detail={detail} />}
          </AsyncBoundary>
        </section>
      </div>
    </div>
  );
}

function ProcessListLabel({ process }: {
  readonly process: ProcessSummary;
}) {
  return (
    <>
      <div>
        <strong>{process.workflow_ref}</strong>
        <small>{process.current_step || "terminal"}{process.has_view ? "" : " - runtime"}</small>
      </div>
      <StatusPill kind={processTone(process.status)} label={process.status} />
    </>
  );
}

function ProcessStatusSummary({ processes }: { readonly processes: readonly ProcessSummary[] }) {
  const active = processes.filter((process) => ["pending", "running", "waiting", "compensating"].includes(process.status)).length;
  const failed = processes.filter((process) => ["failed", "cancelled", "timed_out"].includes(process.status)).length;
  const completed = processes.length - active - failed;
  return (
    <div class="process-status-summary" aria-label="Workflow run summary">
      <span><strong>{processes.length}</strong> runs</span>
      <span><strong>{active}</strong> active</span>
      <span><strong>{completed}</strong> completed</span>
      <span class={failed > 0 ? "is-danger" : undefined}><strong>{failed}</strong> failed</span>
    </div>
  );
}

function ProcessDetail({ detail }: { readonly detail: ProcessDetailData }) {
  const { process, events } = detail.journal;
  return (
    <div class="stack process-detail">
      <header class="process-view-header">
        <div>
          <span class="eyebrow">{process.workflow_ref} <span class="mono">v{process.workflow_version}</span></span>
          <h2>{process.target_resource_id}</h2>
          <p class="muted">Process <span class="mono">{process.id}</span></p>
        </div>
        <div class="process-view-status">
          <StatusPill kind={processTone(process.status)} label={process.status} />
          <span class="mono">{process.current_step || "terminal"}</span>
        </div>
      </header>
      <dl class="process-runtime-meta">
        <div><dt>Started</dt><dd>{formatTimestamp(process.started_at)}</dd></div>
        <div><dt>Updated</dt><dd>{formatTimestamp(process.updated_at)}</dd></div>
        <div><dt>Revision</dt><dd>{process.revision}</dd></div>
        <div><dt>Journal events</dt><dd>{detail.journal.count}</dd></div>
      </dl>
      <ProcessJournal processId={process.id} events={events} />
      {detail.view ? <RenderedProcess view={detail.view} compactHeader /> : (
        <p class="process-generic-note muted">No workflow-specific ViewSpec is registered. The runtime snapshot and journal above remain available for every workflow.</p>
      )}
    </div>
  );
}

function ProcessJournal({
  processId,
  events,
}: {
  readonly processId: string;
  readonly events: readonly ProcessEvent[];
}) {
  const selectedEvent = currentRoute().search.get("event");
  return (
    <section class="process-journal" aria-labelledby="process-journal-title">
      <div class="process-section-heading">
        <div><span class="eyebrow">Execution journal</span><h3 id="process-journal-title">Step timeline</h3></div>
        <span class="muted">oldest to newest</span>
      </div>
      <ol class="process-timeline">
        {events.map((event) => (
          <li key={event.event_id}>
            <span class="process-timeline-marker" aria-hidden="true" />
            <div>
              <div class="process-event-head">
                <strong>{event.kind.replaceAll(".", " ")}</strong>
                <a
                  class="mono small"
                  href={processEventHref(processId, event.event_id)}
                >
                  {event.event_id}
                </a>
                <time dateTime={event.recorded_at}>{formatTimestamp(event.recorded_at)}</time>
              </div>
              <p>{event.step_id ? <span class="mono">{event.step_id}</span> : "Process lifecycle"}{eventSummary(event) ? ` - ${eventSummary(event)}` : ""}</p>
              <details class="process-event-detail" open={selectedEvent === event.event_id}>
                <summary class="details-summary">Recorded event</summary>
                <dl>
                  <div><dt>Event id</dt><dd><code>{event.event_id}</code></dd></div>
                  <div><dt>Correlation</dt><dd><code>{event.correlation_id}</code></dd></div>
                  <div><dt>Causation</dt><dd><code>{event.causation_id ?? "-"}</code></dd></div>
                  <div><dt>Attempt</dt><dd>{event.attempt}</dd></div>
                </dl>
                <pre class="mono small entry-json">{JSON.stringify(event.payload, null, 2)}</pre>
              </details>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

function eventSummary(event: ProcessEvent): string {
  for (const key of ["reason", "outcome", "decision", "terminal_outcome", "branch"]) {
    if (event.payload[key] !== undefined) return displayValue(event.payload[key]);
  }
  return "";
}

function formatTimestamp(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function RenderedProcess({ view, compactHeader = false }: { readonly view: RenderedProcessView; readonly compactHeader?: boolean }) {
  return (
    <div class="stack process-domain-view">
      <header class={compactHeader ? "process-section-heading" : "process-view-header"}>
        <div><span class="eyebrow">{view.process.workflow_ref}</span><h2>{view.name}</h2><p class="muted">{view.description}</p></div>
        {!compactHeader ? <div class="process-view-status"><StatusPill kind={processTone(view.process.status)} label={view.process.status} /><span class="mono">{view.process.current_step || "terminal"}</span></div> : null}
      </header>
      <div class="process-region-grid">
        {view.regions.map((region) => (
          <RenderedRegion key={region.id} span={region.column_span}>
            <div class="process-widget-grid">
              {region.report.widgets.map((widget) => <ProcessWidget key={widget.id} widget={widget} />)}
            </div>
          </RenderedRegion>
        ))}
      </div>
    </div>
  );
}
