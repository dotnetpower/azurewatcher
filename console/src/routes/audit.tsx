import { useEffect, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import type { AuditItem, AuditPage } from "../types";
import {
  AsyncBoundary,
  DataTable,
  PageHeader,
  StatusPill,
  type AsyncState,
  type Column,
  type PillKind,
} from "../components/ui";
import { usePublishViewContext } from "../deck/context";

interface Props {
  readonly client: ReadApiClient;
}

interface Data {
  readonly items: readonly AuditItem[];
  readonly nextCursor: string | null;
}

const PAGE_SIZE = 25;

export function AuditRoute({ client }: Props) {
  const [state, setState] = useState<AsyncState<Data>>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const page = await client.listAudit({ limit: PAGE_SIZE });
        if (!cancelled) {
          setState({
            status: "ready",
            data: { items: page.items, nextCursor: page.next_cursor },
          });
        }
      } catch (err) {
        if (!cancelled) {
          setState({
            status: "error",
            message: err instanceof Error ? err.message : String(err),
          });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [client]);

  const loadMore = async (cursor: string): Promise<void> => {
    if (state.status !== "ready") return;
    try {
      const page: AuditPage = await client.listAudit({
        limit: PAGE_SIZE,
        cursor,
      });
      setState({
        status: "ready",
        data: {
          items: [...state.data.items, ...page.items],
          nextCursor: page.next_cursor,
        },
      });
    } catch (err) {
      setState({
        status: "error",
        message: err instanceof Error ? err.message : String(err),
      });
    }
  };

  return (
    <div class="stack">
      <PageHeader
        title="Audit log"
        subtitle="Append-only record of every terminal control-plane decision. Read-only; entries are never edited or deleted."
      />
      <AsyncBoundary state={state} resourceLabel="audit log">
        {(data) => <AuditBody data={data} onLoadMore={loadMore} />}
      </AsyncBoundary>
    </div>
  );
}

function modePill(mode: string): PillKind {
  if (mode === "enforce") return "enforce";
  if (mode === "shadow") return "shadow";
  return "neutral";
}

interface BodyProps {
  readonly data: Data;
  readonly onLoadMore: (cursor: string) => Promise<void>;
}

function AuditBody({ data, onLoadMore }: BodyProps) {
  usePublishViewContext(
    () => ({
      routeId: "audit",
      routeLabel: "Audit log",
      headline: `${data.items.length} row(s) loaded${data.nextCursor === null ? " (end of log)" : " (more available)"}`,
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "loaded_rows", value: data.items.length, group: "page" },
        { key: "more_available", value: data.nextCursor !== null, group: "page" },
      ],
      records: {
        items: data.items.map((r) => ({
          seq: r.seq,
          recorded_at: r.recorded_at,
          actor: r.actor,
          action_kind: r.action_kind,
          mode: r.mode,
          event_id: r.event_id,
        })),
      },
    }),
    [data.items, data.nextCursor],
  );

  const columns: readonly Column<AuditItem>[] = [
    { key: "seq", header: "#", render: (r) => r.seq, cellClass: "mono num", headerClass: "num" },
    { key: "at", header: "Recorded at", render: (r) => r.recorded_at, cellClass: "mono" },
    { key: "actor", header: "Actor", render: (r) => r.actor },
    { key: "kind", header: "Action kind", render: (r) => r.action_kind, cellClass: "mono" },
    {
      key: "mode",
      header: "Mode",
      render: (r) => <StatusPill kind={modePill(r.mode)} label={r.mode} />,
    },
    { key: "eid", header: "Event id", render: (r) => r.event_id, cellClass: "mono" },
    {
      key: "raw",
      header: "Details",
      render: (r) => (
        <details>
          <summary class="details-summary">view JSON</summary>
          <pre class="mono small entry-json">{JSON.stringify(r.entry, null, 2)}</pre>
        </details>
      ),
    },
  ];

  return (
    <div class="stack">
      <DataTable
        columns={columns}
        rows={data.items}
        keyOf={(r) => r.seq}
        empty="Audit log is empty."
      />
      {data.nextCursor !== null ? (
        <button
          type="button"
          class="primary"
          onClick={() => {
            void onLoadMore(data.nextCursor!);
          }}
        >
          Load more
        </button>
      ) : (
        <p class="muted footnote">End of log.</p>
      )}
    </div>
  );
}
