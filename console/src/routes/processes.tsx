import { useEffect, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import { AsyncBoundary, EmptyState, PageHeader, StatusPill, type AsyncState } from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { t } from "../i18n";
import { currentRoute, routeHref } from "../router";
import { ProcessWidget, RenderedRegion } from "./process-view-renderer";
import {
  decodeProcessList,
  decodeProcessJournal,
  decodeRenderedProcessView,
    displayValue,
    type ProcessDetailData,
    type ProcessEvent,
  defaultProcessId,
  processHref,
  processIdFromHash,
  processListFailure,
  processTone,
  type ProcessListResponse,
  type ProcessSummary,
  type RenderedProcessView,
} from "./processes.model";

interface Props { readonly client: ReadApiClient }

export function ProcessesRoute({ client }: Props) {
  const [listState, setListState] = useState<AsyncState<ProcessListResponse>>({ status: "loading" });
  const [selectedId, setSelectedId] = useState<string | null>(() => currentRoute().segments[0] ?? null);
  const [detailState, setDetailState] = useState<AsyncState<ProcessDetailData>>({ status: "idle" });
  const [refreshKey, setRefreshKey] = useState(0);

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
          return;
        }
        setListState({ status: "ready", data });
        const defaultId = currentRoute().segments[0] ?? defaultProcessId(data.items, "");
        if (!currentRoute().segments[0] && defaultId) {
          window.history.replaceState(window.history.state, "", processHref(defaultId));
          setSelectedId(defaultId);
        }
      },
      (error: unknown) => {
        if (cancelled) return;
        setListState(processListFailure(error));
      },
    );
    return () => { cancelled = true; };
  }, [client, refreshKey]);

  useEffect(() => {
    if (!selectedId) { setDetailState({ status: "idle" }); return; }
    const selected = listState.status === "ready"
      ? listState.data.items.find((item) => item.id === selectedId)
      : undefined;
    let cancelled = false;
    setDetailState({ status: "loading" });
    const encodedId = encodeURIComponent(selectedId);
    Promise.all([
      client.panel<unknown>(`/views/process/${encodedId}/events`),
      selected?.has_view
        ? client.panel<unknown>(`/views/process/${encodedId}`)
        : Promise.resolve(null),
    ]).then(
      ([journalPayload, viewPayload]) => {
        if (cancelled) return;
        try {
          setDetailState({
            status: "ready",
            data: {
              journal: decodeProcessJournal(journalPayload),
              view: viewPayload === null ? null : decodeRenderedProcessView(viewPayload),
            },
          });
        } catch (error) {
          setDetailState({ status: "error", message: error instanceof Error ? error.message : String(error) });
        }
      },
      (error: unknown) => { if (!cancelled) setDetailState({ status: "error", message: error instanceof Error ? error.message : String(error) }); },
    );
    return () => { cancelled = true; };
  }, [client, selectedId, listState, refreshKey]);

  return (
    <div class="stack process-route">
      <PageHeader
        title={t("route.processes")}
        subtitle="Workflow run status from authoritative Process snapshots and append-only journals. Execution remains outside the console."
        actions={
          <button type="button" class="btn btn-small" onClick={() => setRefreshKey((value) => value + 1)}>
            Refresh status
          </button>
        }
      />
      <AsyncBoundary state={listState} resourceLabel="processes">
        {(data) => <ProcessWorkspace processes={data.items} selectedId={selectedId} detailState={detailState} />}
      </AsyncBoundary>
    </div>
  );
}

function ProcessWorkspace({ processes, selectedId, detailState }: {
  readonly processes: readonly ProcessSummary[];
  readonly selectedId: string | null;
  readonly detailState: AsyncState<ProcessDetailData>;
}) {
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
    [processes, selected],
  );
  if (processes.length === 0) {
    return <EmptyState title="No workflow processes" body="Process runs appear here after the workflow runtime records them." />;
  }
  const hasRenderableProcess = processes.some((process) => process.has_view);
  return (
    <div class="stack process-status-workspace">
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
                  href={routeHref("processes", {
                    segments: [processId],
                    params: { event: event.event_id },
                  })}
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
