import { useEffect, useMemo, useState } from "preact/hooks";
import { isOptionalReadApiUnavailable, ReadApiError } from "../api";
import type { ReadApiClient } from "../api";
import {
  AsyncBoundary,
  DataTable,
  KpiCard,
  KpiGrid,
  PageHeader,
  StatusPill,
  type AsyncState,
  type Column,
} from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { t } from "../i18n";
import { currentRoute, navigate, routeHref } from "../router";
import { panelArray, panelBoolean, panelNumber, panelRecord, panelString, panelStringArray } from "./panel-decode";

/**
 * Promotion-gate dashboard panel. Fetches ``GET /kpi/promotion-gates``
 * and renders per-ActionType progress against the shipped
 * ``promotion_gate`` block.
 */

interface Row {
  readonly action_type_name: string;
  readonly shadow_days_elapsed: number;
  readonly sample_count: number;
  readonly reviewed_count: number;
  readonly agreed_count: number;
  readonly policy_escapes: number;
  readonly accuracy: number;
  readonly ready: boolean;
  readonly gaps: readonly string[];
}

interface Response {
  readonly window_days: number | null;
  readonly rows: readonly Row[];
  readonly ready_count: number;
  readonly blocked_count: number;
}

interface Props {
  readonly client: ReadApiClient;
}

export function PromotionGatesRoute({ client }: Props) {
  const [state, setState] = useState<AsyncState<Response>>({ status: "loading" });
  const initialStatus = currentRoute().search.get("status");
  const [statusFilter, setStatusFilter] = useState<"all" | "ready" | "blocked">(
    initialStatus === "ready" || initialStatus === "blocked" ? initialStatus : "all",
  );
  const [query, setQuery] = useState(() => currentRoute().search.get("q") ?? "");

  useEffect(() => {
    const sync = () => {
      const status = currentRoute().search.get("status");
      setStatusFilter(status === "ready" || status === "blocked" ? status : "all");
      setQuery(currentRoute().search.get("q") ?? "");
    };
    window.addEventListener("popstate", sync);
    window.addEventListener("fdai:route-changed", sync);
    return () => {
      window.removeEventListener("popstate", sync);
      window.removeEventListener("fdai:route-changed", sync);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = decodePromotionGates(await client.panel<unknown>("/kpi/promotion-gates"));
        if (!cancelled) setState({ status: "ready", data });
      } catch (err) {
        if (!cancelled) {
          const message = err instanceof Error ? err.message : String(err);
          if (isOptionalReadApiUnavailable(err)) {
            setState({
              status: "unavailable",
              message:
                "Promotion-gate dashboard route is not wired on this deployment. " +
                "Set ReadApiConfig.promotion_gate_source in the composition root to enable it.",
            });
          } else {
            setState({ status: "error", message });
          }
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [client]);

  return (
    <div class="stack governance-route promotion-route">
      <PageHeader
        title={t("route.promotionGates")}
        subtitle="Per-ActionType readiness against each shipped promotion_gate. Actions promote from shadow to enforce only when every gap is closed."
      />
      <AsyncBoundary state={state} resourceLabel="promotion gates">
        {(data) => <PromotionBody
          data={data}
          statusFilter={statusFilter}
          query={query}
          onStatus={(status) => navigate(routeHref("promotion-gates", {
            params: { status: status === "all" ? null : status, q: query || null },
          }))}
          onQuery={(nextQuery) => navigate(routeHref("promotion-gates", {
            params: {
              status: statusFilter === "all" ? null : statusFilter,
              q: nextQuery || null,
            },
          }), true)}
        />}
      </AsyncBoundary>
    </div>
  );
}

export function decodePromotionGates(value: unknown): Response {
  const root = panelRecord(value, "promotion gates");
  const windowDays = root["window_days"];
  if (windowDays !== null && (typeof windowDays !== "number" || !Number.isFinite(windowDays))) {
    throw new ReadApiError(502, "invalid read API response: promotion gates.window_days MUST be a number or null");
  }
  return {
    window_days: windowDays,
    ready_count: panelNumber(root, "ready_count", "promotion gates"),
    blocked_count: panelNumber(root, "blocked_count", "promotion gates"),
    rows: panelArray(root["rows"], "promotion gates.rows").map((value, index) => {
      const row = panelRecord(value, `promotion gates.rows[${index}]`);
      return {
        action_type_name: panelString(row, "action_type_name", "promotion gate row"),
        shadow_days_elapsed: panelNumber(row, "shadow_days_elapsed", "promotion gate row"),
        sample_count: panelNumber(row, "sample_count", "promotion gate row"),
        reviewed_count: panelNumber(row, "reviewed_count", "promotion gate row"),
        agreed_count: panelNumber(row, "agreed_count", "promotion gate row"),
        policy_escapes: panelNumber(row, "policy_escapes", "promotion gate row"),
        accuracy: panelNumber(row, "accuracy", "promotion gate row"),
        ready: panelBoolean(row, "ready", "promotion gate row"),
        gaps: panelStringArray(row["gaps"], "promotion gate row.gaps"),
      };
    }),
  };
}

function PromotionBody({
  data,
  statusFilter,
  query,
  onStatus,
  onQuery,
}: {
  readonly data: Response;
  readonly statusFilter: "all" | "ready" | "blocked";
  readonly query: string;
  readonly onStatus: (status: "all" | "ready" | "blocked") => void;
  readonly onQuery: (query: string) => void;
}) {
  const rows = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    return data.rows.filter((row) => {
      if (statusFilter === "ready" && !row.ready) return false;
      if (statusFilter === "blocked" && row.ready) return false;
      return !needle || row.action_type_name.toLocaleLowerCase().includes(needle) ||
        row.gaps.some((gap) => gap.toLocaleLowerCase().includes(needle));
    });
  }, [data.rows, statusFilter, query]);
  usePublishViewContext(
    () => ({
      routeId: "promotion-gates",
      routeLabel: "Promotion gates",
      purpose:
        "Which ActionTypes running in shadow mode have met their promotion gate " +
        "(measured accuracy with zero policy escapes) and are ready to enforce, " +
        "and which are still blocked and why. Read-only: promotion itself is a " +
        "separately reviewed change.",
      glossary: composeGlossary([
        TERMS.actionType,
        TERMS.shadowMode,
        TERMS.mode,
        TERMS.gateDecision,
      ]),
      headline: `${data.ready_count} ready - ${data.blocked_count} blocked${data.window_days !== null ? ` (window ${data.window_days}d)` : ""}`,
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "ready_count", value: data.ready_count, group: "summary" },
        { key: "blocked_count", value: data.blocked_count, group: "summary" },
        { key: "window_days", value: data.window_days, group: "summary" },
      ],
      records: {
        rows: data.rows.map((r) => ({
          action_type_name: r.action_type_name,
          ready: r.ready,
          shadow_days_elapsed: r.shadow_days_elapsed,
          sample_count: r.sample_count,
          reviewed_count: r.reviewed_count,
          agreed_count: r.agreed_count,
          accuracy: r.accuracy,
          policy_escapes: r.policy_escapes,
          gaps: r.gaps,
        })),
      },
    }),
    [data],
  );

  const columns: readonly Column<Row>[] = [
    {
      key: "at",
      header: "ActionType",
      render: (r) => (
        <a href={routeHref("workflow-builder", { params: { action: r.action_type_name } })}>
          {r.action_type_name}
        </a>
      ),
      cellClass: "mono",
    },
    {
      key: "rd",
      header: "Status",
      render: (r) => (
        <StatusPill
          kind={r.ready ? "success" : "warning"}
          label={r.ready ? "ready" : "blocked"}
        />
      ),
    },
    {
      key: "days",
      header: "Shadow days",
      render: (r) => r.shadow_days_elapsed.toFixed(2),
      cellClass: "num", headerClass: "num",
    },
    { key: "samp", header: "Samples", render: (r) => r.sample_count, cellClass: "num", headerClass: "num" },
    {
      key: "rev",
      header: "Reviewed / agreed",
      render: (r) => (
        <PromotionMeter
          value={r.reviewed_count > 0 ? r.agreed_count / r.reviewed_count : 0}
          label={`${r.reviewed_count} / ${r.agreed_count}`}
          tone={r.reviewed_count > 0 && r.agreed_count === r.reviewed_count ? "good" : "warn"}
        />
      ),
    },
    {
      key: "acc",
      header: "Accuracy",
      render: (r) => (
        <PromotionMeter
          value={r.accuracy}
          label={`${(r.accuracy * 100).toFixed(1)}%`}
          tone={r.accuracy >= 0.95 ? "good" : "warn"}
        />
      ),
    },
    {
      key: "esc",
      header: "Policy escapes",
      render: (r) => (
        r.policy_escapes > 0
          ? <StatusPill kind="danger" label={String(r.policy_escapes)} />
          : <span class="muted">0</span>
      ),
      cellClass: "num", headerClass: "num",
    },
    {
      key: "gaps",
      header: "Gaps",
      render: (r) =>
        r.gaps.length === 0
          ? <span class="muted">-</span>
          : (
            <div class="promotion-gaps">
              {r.gaps.map((gap) => <span key={gap}>{gap}</span>)}
            </div>
          ),
    },
    {
      key: "gate",
      header: "Gate",
      render: (r) => (
        <span class={`promotion-gate ${r.ready ? "is-ready" : "is-blocked"}`}>
          <strong>{r.ready ? "gate green" : "blocked"}</strong>
          <small>{r.ready ? "promote via reviewed PR" : "address recorded gaps"}</small>
        </span>
      ),
    },
  ];

  return (
    <div class="stack">
      <div class="governance-readonly-banner">
        <strong>Shadow before enforce.</strong>
        <span>Promotion is a separately reviewed catalog PR. This screen only renders measured readiness.</span>
      </div>
      <KpiGrid>
        <KpiCard label="In shadow" value={data.rows.length} hint="ActionTypes measured in this window" />
        <KpiCard
          label="Ready for promotion"
          value={data.ready_count}
          tone={data.ready_count > 0 ? "positive" : "default"}
          hint="every gate cleared"
        />
        <KpiCard
          label="Blocked"
          value={data.blocked_count}
          tone={data.blocked_count > 0 ? "warning" : "positive"}
          hint="still in shadow"
        />
        <KpiCard
          label="Measurement window"
          value={data.window_days !== null ? `${data.window_days}d` : "-"}
        />
      </KpiGrid>
      <section class="governance-filterbar" aria-label="Promotion gate filters">
        <div class="governance-chipset">
          {(["all", "ready", "blocked"] as const).map((status) => (
            <button
              key={status}
              type="button"
              class={statusFilter === status ? "is-active" : undefined}
              aria-pressed={statusFilter === status}
              onClick={() => onStatus(status)}
            >
              {status}
            </button>
          ))}
        </div>
        <label>
          <span class="sr-only">Search promotion gates</span>
          <input
            type="search"
            value={query}
            placeholder="ActionType or recorded gap"
            onInput={(event) => onQuery(event.currentTarget.value)}
          />
        </label>
      </section>
      <section class="stack-section">
        <h3 class="section-title">ActionTypes ({rows.length})</h3>
        <DataTable
          columns={columns}
          rows={rows}
          keyOf={(r) => r.action_type_name}
          empty="No ActionTypes declared a promotion gate."
        />
      </section>
    </div>
  );
}

function PromotionMeter({
  value,
  label,
  tone,
}: {
  readonly value: number;
  readonly label: string;
  readonly tone: "good" | "warn";
}) {
  return (
    <span class={`promotion-meter is-${tone}`}>
      <span>{label}</span>
      <i><b style={`width:${Math.max(0, Math.min(100, value * 100))}%`} /></i>
    </span>
  );
}
