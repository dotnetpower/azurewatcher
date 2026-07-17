import { useEffect, useRef, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import {
  AsyncBoundary,
  DataTable,
  EmptyState,
  PageHeader,
  StatusPill,
  type AsyncState,
  type Column,
} from "../components/ui";
import { t } from "../i18n";
import { currentRoute, navigate, routeHref } from "../router";
import { schedulerRunsText } from "./scheduler-runs.i18n";
import {
  appendSchedulerRunPage,
  decodeSchedulerRunPage,
  formatSchedulerTimestamp,
  schedulerRunTone,
  type SchedulerRunItem,
  type SchedulerRunPage,
  type SchedulerRunStatus,
} from "./scheduler-runs.model";

interface Query {
  readonly taskId: string;
  readonly status: SchedulerRunStatus | "";
}

const PAGE_SIZE = 50;

export function SchedulerRunsRoute({ client }: { readonly client: ReadApiClient }) {
  const initial = queryFromRoute();
  const [taskInput, setTaskInput] = useState(initial.taskId);
  const [statusInput, setStatusInput] = useState<Query["status"]>(initial.status);
  const [activeQuery, setActiveQuery] = useState<Query | null>(initial.taskId ? initial : null);
  const [state, setState] = useState<AsyncState<SchedulerRunPage>>(
    initial.taskId ? { status: "loading" } : { status: "idle" },
  );
  const [loadingMore, setLoadingMore] = useState(false);
  const [pageError, setPageError] = useState<string | null>(null);
  const generation = useRef(0);

  const load = async (query: Query, cursor: string | null, append: boolean): Promise<void> => {
    const request = append ? generation.current : ++generation.current;
    setPageError(null);
    if (append) setLoadingMore(true);
    else setState({ status: "loading" });
    try {
      const payload = await client.panel<unknown>("/scheduler-runs", {
        task_id: query.taskId,
        limit: String(PAGE_SIZE),
        ...(query.status ? { status: query.status } : {}),
        ...(cursor ? { cursor } : {}),
      });
      const page = decodeSchedulerRunPage(payload);
      if (request !== generation.current) return;
      setState((current) => append && current.status === "ready"
        ? {
            status: "ready",
            data: cursor === null
              ? current.data
              : appendSchedulerRunPage(current.data, cursor, page),
          }
        : { status: "ready", data: page });
    } catch (error) {
      if (request !== generation.current) return;
      if (append) {
        setPageError(error instanceof Error ? error.message : String(error));
      } else {
        setState({
          status: "error",
          message: error instanceof Error ? error.message : String(error),
        });
      }
    } finally {
      if (request === generation.current) setLoadingMore(false);
    }
  };

  useEffect(() => {
    if (activeQuery !== null) void load(activeQuery, null, false);
    return () => { generation.current += 1; };
  }, [client]);

  const submit = (event: Event): void => {
    event.preventDefault();
    const taskId = taskInput.trim();
    if (!taskId) return;
    const query = { taskId, status: statusInput };
    setActiveQuery(query);
    navigate(routeHref("processes", {
      segments: ["scheduler-runs"],
      params: { task_id: taskId, status: statusInput || null },
    }), true);
    void load(query, null, false);
  };

  return (
    <div class="stack scheduler-runs-route">
      <PageHeader
        title={schedulerRunsText("title")}
        subtitle={schedulerRunsText("subtitle")}
      />
      <form class="scheduler-runs-filter" onSubmit={submit}>
        <label>
          <span>{schedulerRunsText("taskId")}</span>
          <input
            required
            value={taskInput}
            onInput={(event) => setTaskInput((event.currentTarget as HTMLInputElement).value)}
          />
        </label>
        <label>
          <span>{schedulerRunsText("status")}</span>
          <select
            value={statusInput}
            onChange={(event) => setStatusInput(event.currentTarget.value as Query["status"])}
          >
            <option value="">{schedulerRunsText("allStatuses")}</option>
            <option value="claimed">claimed</option>
            <option value="published">published</option>
            <option value="failed">failed</option>
            <option value="lost">lost</option>
          </select>
        </label>
        <button type="submit" class="btn" disabled={state.status === "loading"}>
          {schedulerRunsText("lookup")}
        </button>
      </form>
      <AsyncBoundary
        state={state}
        resourceLabel={schedulerRunsText("resourceLabel")}
        idle={<EmptyState title={schedulerRunsText("idle")} />}
      >
        {(page) => (
          <SchedulerRunsTable
            page={page}
            loadingMore={loadingMore}
            pageError={pageError}
            onLoadMore={() => {
              if (activeQuery && page.next_cursor) {
                void load(activeQuery, page.next_cursor, true);
              }
            }}
          />
        )}
      </AsyncBoundary>
    </div>
  );
}

function SchedulerRunsTable({ page, loadingMore, pageError, onLoadMore }: {
  readonly page: SchedulerRunPage;
  readonly loadingMore: boolean;
  readonly pageError: string | null;
  readonly onLoadMore: () => void;
}) {
  const columns: readonly Column<SchedulerRunItem>[] = [
    {
      key: "run",
      header: schedulerRunsText("runId"),
      render: (item) => item.run_id,
      cellClass: "mono",
    },
    {
      key: "scheduled",
      header: schedulerRunsText("scheduledFor"),
      render: (item) => formatSchedulerTimestamp(item.scheduled_for),
    },
    {
      key: "status",
      header: schedulerRunsText("status"),
      render: (item) => (
        <StatusPill kind={schedulerRunTone(item.status)} label={item.status} />
      ),
    },
    {
      key: "attempt",
      header: schedulerRunsText("attempt"),
      render: (item) => item.attempt,
      cellClass: "num",
    },
    {
      key: "completed",
      header: schedulerRunsText("completedAt"),
      render: (item) => formatSchedulerTimestamp(item.completed_at),
    },
    {
      key: "error",
      header: schedulerRunsText("errorKind"),
      render: (item) => item.error_kind ?? "-",
      cellClass: "mono",
    },
  ];
  return (
    <section
      class="stack-section"
      aria-label={schedulerRunsText("tableLabel", { taskId: page.task_id })}
    >
      <div class="filter-summary" aria-label={schedulerRunsText("provenanceLabel")}>
        <span>{schedulerRunsText("source")}: <strong>{page.source}</strong></span>
        <span>{schedulerRunsText("storage")}: <strong>
          {schedulerRunsText(page.durable ? "durable" : "volatile")}
        </strong></span>
      </div>
      <DataTable
        columns={columns}
        rows={page.items}
        keyOf={(item) => `${item.run_id}:${item.attempt}`}
        empty={<EmptyState title={schedulerRunsText("empty")} />}
      />
      {page.next_cursor ? (
        <button type="button" class="btn" disabled={loadingMore} onClick={onLoadMore}>
          {loadingMore ? schedulerRunsText("loadingMore") : schedulerRunsText("loadMore")}
        </button>
      ) : null}
      {pageError ? (
        <div class="error" role="alert">
          {schedulerRunsText("loadMoreError", { message: pageError })}
        </div>
      ) : null}
    </section>
  );
}

function queryFromRoute(): Query {
  const search = currentRoute().search;
  const status = search.get("status");
  return {
    taskId: search.get("task_id") ?? "",
    status: status === "claimed" || status === "published" || status === "failed" || status === "lost"
      ? status
      : "",
  };
}
