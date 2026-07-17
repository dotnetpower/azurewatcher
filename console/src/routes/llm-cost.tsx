import { useEffect, useState } from "preact/hooks";
import { isOptionalReadApiUnavailable } from "../api";
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
import { getLocale } from "../i18n";
import { t } from "./i18n/llm-cost";
import { routeHref } from "../router";
import {
  panelArray,
  panelBoolean,
  panelNullableString,
  panelNumber,
  panelRecord,
  panelString,
} from "./panel-decode";

/**
 * LLM cost panel. Fetches ``GET /kpi/llm-cost`` and renders measured
 * token usage + spend grouped per conversation, per day, and per month.
 *
 * Read-only: every number comes from the metering stream (recorded from
 * real provider ``usage``); there is no action button. The ``source``
 * field is surfaced honestly - ``metering`` for a real store, or
 * ``synthetic-dev`` in the dev harness where LLM calls are faked.
 */

interface Summary {
  readonly key: string;
  readonly invocations: number;
  readonly priced_invocations: number;
  readonly prompt_tokens: number;
  readonly completion_tokens: number;
  readonly total_tokens: number;
  readonly cost: string;
  readonly currency: string;
  readonly has_unpriced: boolean;
  readonly has_mixed_currency: boolean;
}

interface Response {
  readonly source: string;
  readonly latest_occurred_at: string | null;
  readonly currency: string;
  readonly invocations: number;
  readonly total: Summary;
  readonly by_mode: readonly Summary[];
  readonly by_conversation: readonly Summary[];
  readonly by_conversation_truncated: boolean;
  readonly conversation_count: number;
  readonly by_day: readonly Summary[];
  readonly by_month: readonly Summary[];
}

interface Props {
  readonly client: ReadApiClient;
}

export function formatLlmCost(s: Pick<Summary, "cost" | "currency" | "has_mixed_currency">): string {
  return s.has_mixed_currency ? t("llmCost.mixedCurrencies") : `${s.cost} ${s.currency}`;
}

export function LlmCostRoute({ client }: Props) {
  const [state, setState] = useState<AsyncState<Response>>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = decodeLlmCost(await client.panel<unknown>("/kpi/llm-cost"));
        if (!cancelled) setState({ status: "ready", data });
      } catch (err) {
        if (!cancelled) {
          const message = err instanceof Error ? err.message : String(err);
          if (isOptionalReadApiUnavailable(err)) {
            setState({
              status: "unavailable",
              message: t("llmCost.unavailable"),
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
    <div class="stack analytics-route">
      <PageHeader title={t("route.llmCost")} subtitle={t("nav.panelSub.llmCost")} />
      <AsyncBoundary state={state} resourceLabel={t("route.llmCost")}>
        {(data) => <LlmCostBody data={data} />}
      </AsyncBoundary>
    </div>
  );
}

export function decodeLlmCost(value: unknown): Response {
  const root = panelRecord(value, "LLM cost");
  const decodeSummary = (value: unknown, label: string): Summary => {
    const summary = panelRecord(value, label);
    return {
      key: panelString(summary, "key", label),
      invocations: panelNumber(summary, "invocations", label),
      priced_invocations: panelNumber(summary, "priced_invocations", label),
      prompt_tokens: panelNumber(summary, "prompt_tokens", label),
      completion_tokens: panelNumber(summary, "completion_tokens", label),
      total_tokens: panelNumber(summary, "total_tokens", label),
      cost: panelString(summary, "cost", label),
      currency: panelString(summary, "currency", label),
      has_unpriced: panelBoolean(summary, "has_unpriced", label),
      has_mixed_currency: panelBoolean(summary, "has_mixed_currency", label),
    };
  };
  const summaries = (key: string) => panelArray(root[key], `LLM cost.${key}`)
    .map((item, index) => decodeSummary(item, `LLM cost.${key}[${index}]`));
  return {
    source: panelString(root, "source", "LLM cost"),
    latest_occurred_at: panelNullableString(root, "latest_occurred_at", "LLM cost"),
    currency: panelString(root, "currency", "LLM cost"),
    invocations: panelNumber(root, "invocations", "LLM cost"),
    total: decodeSummary(root["total"], "LLM cost.total"),
    by_mode: summaries("by_mode"),
    by_conversation: summaries("by_conversation"),
    by_conversation_truncated: panelBoolean(root, "by_conversation_truncated", "LLM cost"),
    conversation_count: panelNumber(root, "conversation_count", "LLM cost"),
    by_day: summaries("by_day"),
    by_month: summaries("by_month"),
  };
}

export function llmCostCorrelationHref(correlationId: string): string {
  return routeHref("audit", { params: { correlation: correlationId } });
}

function _summaryColumns(
  keyHeader: string,
  keyHref?: (key: string) => string,
): readonly Column<Summary>[] {
  return [
    {
      key: "k",
      header: keyHeader,
      render: (r) => keyHref ? <a href={keyHref(r.key)}>{r.key}</a> : r.key,
      cellClass: "mono",
    },
    { key: "inv", header: t("llmCost.column.calls"), render: (r) => r.invocations },
    { key: "pt", header: t("llmCost.column.prompt"), render: (r) => r.prompt_tokens.toLocaleString(getLocale() === "ko" ? "ko-KR" : "en-US") },
    { key: "ct", header: t("llmCost.column.completion"), render: (r) => r.completion_tokens.toLocaleString(getLocale() === "ko" ? "ko-KR" : "en-US") },
    { key: "tt", header: t("llmCost.totalTokens"), render: (r) => r.total_tokens.toLocaleString(getLocale() === "ko" ? "ko-KR" : "en-US") },
    {
      key: "cost",
      header: t("llmCost.column.cost"),
      render: (r) =>
        r.has_mixed_currency ? (
          <span>
            {formatLlmCost(r)} <StatusPill kind="warning" label={t("llmCost.notAdditive")} />
          </span>
        ) : r.has_unpriced ? (
          <span>
            {formatLlmCost(r)} <StatusPill kind="warning" label={t("llmCost.partial")} />
          </span>
        ) : (
          formatLlmCost(r)
        ),
    },
  ];
}

function LlmCostBody({ data }: { readonly data: Response }) {
  const locale = getLocale() === "ko" ? "ko-KR" : "en-US";
  usePublishViewContext(
    () => ({
      routeId: "llm-cost",
      routeLabel: t("route.llmCost"),
      purpose:
        "Measured LLM token usage and spend, rolled up per conversation, per " +
        "day, and per month. Read-only: it reports recorded usage, it does not " +
        "cap spend (the model budget cap does that upstream).",
      glossary: composeGlossary([
        TERMS.tier,
        TERMS.mode,
        TERMS.hil,
      ]),
      headline: `${data.total.total_tokens.toLocaleString(locale)} tokens - ${formatLlmCost(data.total)} (${data.source})`,
      capturedAt: data.latest_occurred_at ?? new Date().toISOString(),
      facts: [
        { key: "source", value: data.source, group: "summary" },
        { key: "latest_occurred_at", value: data.latest_occurred_at, group: "summary" },
        { key: "invocations", value: data.invocations, group: "summary" },
        { key: "total_tokens", value: data.total.total_tokens, group: "summary" },
        { key: "total_cost", value: formatLlmCost(data.total), group: "summary" },
        { key: "mixed_currency", value: data.total.has_mixed_currency, group: "summary" },
      ],
      records: {
        by_month: data.by_month.map((r) => ({ ...r })),
        by_day: data.by_day.map((r) => ({ ...r })),
        by_conversation: data.by_conversation.map((r) => ({ ...r })),
      },
    }),
    [data],
  );

  return (
    <div class="stack">
      <KpiGrid>
        <KpiCard label={t("llmCost.source")} value={data.source} />
        <KpiCard
          label={t("llmCost.latestInvocation")}
          value={data.latest_occurred_at ? new Date(data.latest_occurred_at).toLocaleString(locale) : t("llmCost.valueUnavailable")}
        />
        <KpiCard label={t("llmCost.calls")} value={data.invocations.toLocaleString(locale)} />
        <KpiCard label={t("llmCost.totalTokens")} value={data.total.total_tokens.toLocaleString(locale)} />
        <KpiCard
          label={t("llmCost.totalCost")}
          value={formatLlmCost(data.total)}
          tone={data.total.has_mixed_currency ? "warning" : "default"}
          hint={data.total.has_mixed_currency ? t("llmCost.mixedCurrencyHint") : undefined}
        />
      </KpiGrid>

      <section class="stack">
        <h3>{t("llmCost.byMode")}</h3>
        <DataTable
          rows={data.by_mode}
          columns={_summaryColumns(t("llmCost.column.mode"))}
          keyOf={(r) => r.key}
          empty={t("llmCost.empty")}
        />
      </section>

      <section class="stack">
        <h3>{t("llmCost.byMonth")}</h3>
        <DataTable
          rows={data.by_month}
          columns={_summaryColumns(t("llmCost.column.month"))}
          keyOf={(r) => r.key}
          empty={t("llmCost.empty")}
        />
      </section>

      <section class="stack">
        <h3>{t("llmCost.byDay")}</h3>
        <DataTable
          rows={data.by_day}
          columns={_summaryColumns(t("llmCost.column.day"))}
          keyOf={(r) => r.key}
          empty={t("llmCost.empty")}
        />
      </section>

      <section class="stack">
        <h3>{t("llmCost.byConversation")}</h3>
        {data.by_conversation_truncated ? (
          <p class="muted">
            {t("llmCost.truncated", {
              shown: data.by_conversation.length,
              total: data.conversation_count,
            })}
          </p>
        ) : null}
        <DataTable
          rows={data.by_conversation}
          columns={_summaryColumns(t("llmCost.column.conversationId"), llmCostCorrelationHref)}
          keyOf={(r) => r.key}
          empty={t("llmCost.empty")}
        />
      </section>
    </div>
  );
}
