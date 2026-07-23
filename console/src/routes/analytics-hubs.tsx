import type { ReadApiClient } from "../api";
import type { AutonomyPayload } from "../types";
import { usePublishViewContext } from "../deck/context";
import {
  AsyncBoundary,
  DataTable,
  KpiCard,
  KpiGrid,
  PageHeader,
  StatusPill,
  UnavailableState,
  kpiEvidenceLabel,
  type Column,
} from "../components/ui";
import { getLocale } from "../i18n";
import { t } from "./i18n/analytics";
import { currentRoute, routeHref } from "../router";
import { formatShare } from "./dashboard.model";
import { useAnalyticsData, type AnalyticsData } from "./analytics-data";
import { buildOperatingOutcomeViewSnapshot } from "./analytics-hubs.view";
import { ControlAssuranceBody } from "./control-assurance";
import { VerticalOutcomesBody } from "./vertical-outcomes";
export { formatMeasuredSavings, verticalResolutionRate } from "./vertical-outcomes";
import {
  OperatingOutcomeBody,
  OUTCOME_KEYS,
  outcomeMetric,
  type OutcomeKey,
} from "./operating-outcomes";

interface Props { readonly client: ReadApiClient }

export function measuredTierValue(
  values: Readonly<Record<string, number>>,
  tier: string,
): number | null {
  return Object.prototype.hasOwnProperty.call(values, tier) ? values[tier] ?? null : null;
}

export function searchParamsRecord(search: URLSearchParams): Readonly<Record<string, string>> {
  return Object.fromEntries(search.entries());
}

export function routingParamsForTier(
  tier: string,
  search: URLSearchParams,
): Readonly<Record<string, string>> {
  const params = searchParamsRecord(search);
  if (tier === "t2") return params;
  const { indicator: _indicator, ...shared } = params;
  return shared;
}

function HubTabs({
  panelId,
  values,
  active,
  label,
  paramsForValue,
}: {
  readonly panelId: string;
  readonly values: readonly string[];
  readonly active: string;
  readonly label: (value: string) => string;
  readonly paramsForValue?: (value: string, search: URLSearchParams) => Readonly<Record<string, string>>;
}) {
  const search = currentRoute().search;
  return (
    <nav class="analytics-tabs" aria-label={t("analytics.detailViews")}>
      {values.map((value) => (
        <a
          key={value}
          href={routeHref(panelId, {
            segments: [value],
            params: paramsForValue?.(value, search) ?? searchParamsRecord(search),
          })}
          class={value === active ? "active" : undefined}
          aria-current={value === active ? "page" : undefined}
        >
          {label(value)}
        </a>
      ))}
    </nav>
  );
}

function EvidenceStrip({ autonomy }: { readonly autonomy: AutonomyPayload }) {
  const locale = getLocale() === "ko" ? "ko-KR" : "en-US";
  return (
    <div class="analytics-evidence">
      <strong>{autonomy.synthetic ? t("analytics.simulated") : t("analytics.measured")}</strong>
      <span>{t("analytics.window", { days: autonomy.window_days })}</span>
      <span>{t("analytics.samples", { count: autonomy.sample_size.toLocaleString(locale) })}</span>
      <span>
        {autonomy.confidence === null
          ? t("analytics.confidenceUnavailable")
          : t("analytics.confidence", { value: Math.round(autonomy.confidence * 100) })}
      </span>
      <span>{t("overview.evidence.source", { source: autonomy.source.name })}</span>
      {autonomy.source.as_of ? (
        <span>{t("overview.evidence.asOf", { time: autonomy.source.as_of })}</span>
      ) : null}
    </div>
  );
}

export function OperatingOutcomesRoute({ client }: Props) {
  const state = useAnalyticsData(client);
  const segment = currentRoute().segments[0];
  const active: OutcomeKey | null = segment === undefined
    ? "auto-resolution"
    : OUTCOME_KEYS.includes(segment as OutcomeKey) ? segment as OutcomeKey : null;
  return (
    <div class="stack analytics-route">
      <PageHeader title={t("analytics.outcomes.title")} subtitle={t("analytics.outcomes.subtitle")} />
      <HubTabs panelId="operating-outcomes" values={OUTCOME_KEYS} active={active ?? ""} label={(key) => t(`analytics.metric.${key}`)} />
      {active === null ? <UnavailableState message={t("analytics.invalidDetail")} /> : (
        <AsyncBoundary state={state} resourceLabel={t("analytics.outcomes.title")}>
          {(data) => data.autonomy ? <OutcomeBody data={data} active={active} /> : <UnavailableState message={t("analytics.autonomyUnavailable")} />}
        </AsyncBoundary>
      )}
    </div>
  );
}

function OutcomeBody({ data, active }: { readonly data: AnalyticsData; readonly active: OutcomeKey }) {
  const autonomy = data.autonomy!;
  const metric = outcomeMetric(autonomy, active);
  const routeLabel = t("analytics.outcomes.title");
  const metricLabel = t(`analytics.metric.${active}`);
  const unavailableLabel = t("analytics.unavailable");
  usePublishViewContext(
    () => buildOperatingOutcomeViewSnapshot({
      autonomy,
      metric,
      metricKey: active,
      metricLabel,
      unavailableLabel,
      routeLabel,
    }),
    [active, autonomy, metric, metricLabel, routeLabel, unavailableLabel],
  );
  return <OperatingOutcomeBody data={data} active={active} />;
}

export function ControlAssuranceRoute({ client }: Props) {
  const state = useAnalyticsData(client, { includeGates: true });
  const guardKey = currentRoute().search.get("guard");
  return (
    <div class="stack analytics-route">
      <PageHeader title={t("analytics.assurance.title")} subtitle={t("analytics.assurance.subtitle")} />
      <AsyncBoundary state={state} resourceLabel={t("analytics.assurance.title")}>
        {(data) => (
          <ControlAssuranceBody
            data={data}
            evidence={data.autonomy ? <EvidenceStrip autonomy={data.autonomy} /> : null}
            guardKey={guardKey}
            context={searchParamsRecord(currentRoute().search)}
          />
        )}
      </AsyncBoundary>
    </div>
  );
}

const VERTICAL_KEYS = ["resilience", "change-safety", "cost-governance"] as const;

export function VerticalOutcomesRoute({ client }: Props) {
  const state = useAnalyticsData(client);
  const segment = currentRoute().segments[0];
  const active = segment === undefined
    ? "resilience"
    : VERTICAL_KEYS.includes(segment as (typeof VERTICAL_KEYS)[number]) ? segment : null;
  return (
    <div class="stack analytics-route">
      <PageHeader title={t("analytics.verticals.title")} subtitle={t("analytics.verticals.subtitle")} />
      <HubTabs panelId="verticals" values={VERTICAL_KEYS} active={active ?? ""} label={(key) => t(`analytics.vertical.${key}`)} />
      {active === null ? <UnavailableState message={t("analytics.invalidDetail")} /> : (
        <AsyncBoundary state={state} resourceLabel={t("analytics.verticals.title")}>
          {(data) => data.autonomy ? (
            <VerticalOutcomesBody
              active={active}
              autonomy={data.autonomy}
              context={searchParamsRecord(currentRoute().search)}
              evidence={<EvidenceStrip autonomy={data.autonomy} />}
            />
          ) : <UnavailableState message={t("analytics.autonomyUnavailable")} />}
        </AsyncBoundary>
      )}
    </div>
  );
}

const TIER_KEYS = ["t0", "t1", "t2"] as const;
const LEADING_INDICATOR_KEYS = ["disagreement", "verifier", "divergence"] as const;
type LeadingIndicatorKey = (typeof LEADING_INDICATOR_KEYS)[number];

export function TrustRoutingRoute({ client }: Props) {
  const state = useAnalyticsData(client);
  const segment = currentRoute().segments[0]?.toLowerCase();
  const indicatorParam = currentRoute().search.get("indicator");
  const indicator = indicatorParam === null
    ? null
    : LEADING_INDICATOR_KEYS.includes(indicatorParam as LeadingIndicatorKey)
      ? indicatorParam as LeadingIndicatorKey
      : undefined;
  const active = segment === undefined
    ? "t0"
    : TIER_KEYS.includes(segment as (typeof TIER_KEYS)[number]) ? segment : null;
  return (
    <div class="stack analytics-route">
      <PageHeader title={t("analytics.routing.title")} subtitle={t("analytics.routing.subtitle")} />
      <HubTabs
        panelId="trust-routing"
        values={TIER_KEYS}
        active={active ?? ""}
        label={(key) => key.toUpperCase()}
        paramsForValue={routingParamsForTier}
      />
      {active === null ? <UnavailableState message={t("analytics.invalidDetail")} /> : (
        <AsyncBoundary state={state} resourceLabel={t("analytics.routing.title")}>
          {(data) => data.autonomy ? (
            <RoutingBody data={data} active={active} indicator={indicator} />
          ) : <UnavailableState message={t("analytics.autonomyUnavailable")} />}
        </AsyncBoundary>
      )}
    </div>
  );
}

function RoutingBody({
  data,
  active,
  indicator,
}: {
  readonly data: AnalyticsData;
  readonly active: string;
  readonly indicator: LeadingIndicatorKey | null | undefined;
}) {
  const share = measuredTierValue(data.autonomy!.tier.mix, active);
  const band = data.autonomy!.tier.bands[active];
  const count = measuredTierValue(data.kpi.by_tier, active);
  const inBand = band && share !== null ? share >= band[0] && share <= band[1] : null;
  const context = searchParamsRecord(currentRoute().search);
  const auditContext = {
    ...context,
    window: `${data.autonomy!.window_days}d`,
    tier: active,
  };
  const routingHref = routeHref("trust-routing", {
    segments: [active],
    params: routingParamsForTier(active, currentRoute().search),
  });
  return (
    <div class="stack">
      <EvidenceStrip autonomy={data.autonomy!} />
      <KpiGrid>
        <KpiCard evidenceState={share === null ? "not-measured" : "measured"} href={routeHref("audit", { params: auditContext })} label={t("analytics.routing.share")} value={share === null ? kpiEvidenceLabel("not-measured") : formatShare(share)} hint={share === null ? t("analytics.notMeasuredHint") : undefined} />
        <KpiCard evidenceState={band ? "measured" : "not-connected"} href={routingHref} label={t("analytics.routing.targetBand")} value={band ? `${Math.round(band[0] * 100)}-${Math.round(band[1] * 100)}%` : t("analytics.notConfigured")} hint={band ? undefined : t("analytics.notConnectedHint")} />
        <KpiCard evidenceState={count === null ? "not-measured" : "measured"} href={routeHref("audit", { params: auditContext })} label={t("analytics.events")} value={count ?? kpiEvidenceLabel("not-measured")} hint={count === null ? t("analytics.notMeasuredHint") : undefined} />
        <KpiCard evidenceState={inBand === null ? "not-measured" : "measured"} href={routingHref} label={t("analytics.status")} value={inBand === null ? kpiEvidenceLabel("not-measured") : inBand ? t("analytics.inBand") : t("analytics.outOfBand")} hint={inBand === null ? t("analytics.notMeasuredHint") : undefined} tone={inBand === null ? "default" : inBand ? "positive" : "warning"} />
      </KpiGrid>
      <TierTable data={data} />
      {active === "t2" ? (
        <LeadingIndicatorTable autonomy={data.autonomy!} indicator={indicator} />
      ) : indicator !== null ? (
        <UnavailableState message={t("analytics.routing.indicatorT2Only")} />
      ) : null}
      <EvidenceLinks links={[
        [t("analytics.viewAudit"), routeHref("audit", { params: { tier: active } })],
        [t("analytics.viewRules"), routeHref("rules")],
        [t("analytics.viewLlmCost"), routeHref("llm-cost")],
      ]} />
    </div>
  );
}

function LeadingIndicatorTable({
  autonomy,
  indicator,
}: {
  readonly autonomy: AutonomyPayload;
  readonly indicator: LeadingIndicatorKey | null | undefined;
}) {
  if (indicator === undefined) return <UnavailableState message={t("analytics.routing.invalidIndicator")} />;
  const allRows = [
    { key: "disagreement" as const, metric: autonomy.leading.mixed_model_disagreement_rate },
    { key: "verifier" as const, metric: autonomy.leading.verifier_failure_rate },
    { key: "divergence" as const, metric: autonomy.leading.shadow_divergence_rate },
  ];
  const rows = indicator === null ? allRows : allRows.filter((row) => row.key === indicator);
  const columns: readonly Column<(typeof allRows)[number]>[] = [
    { key: "indicator", header: t("analytics.routing.indicator"), render: (row) => t(`overview.leading.${row.key}`) },
    { key: "current", header: t("analytics.current"), render: (row) => row.metric.value === null ? t("analytics.unavailable") : formatShare(row.metric.value), cellClass: "num" },
    { key: "baseline", header: t("analytics.baseline"), render: (row) => row.metric.baseline === null ? t("analytics.unavailable") : formatShare(row.metric.baseline), cellClass: "num" },
    {
      key: "status",
      header: t("analytics.status"),
      render: (row) => autonomy.synthetic
        ? <StatusPill kind="neutral" label={t("analytics.simulatedStatus")} />
        : row.metric.value === null || row.metric.baseline === null
          ? <StatusPill kind="neutral" label={t("analytics.unavailable")} />
          : <StatusPill
              kind={row.metric.value <= row.metric.baseline ? "success" : "warning"}
              label={row.metric.value <= row.metric.baseline ? t("analytics.passing") : t("analytics.outOfBand")}
            />,
    },
  ];
  return (
    <section class="analytics-panel">
      <h3>{t("analytics.routing.leadingIndicators")}</h3>
      <DataTable columns={columns} rows={rows} keyOf={(row) => row.key} />
    </section>
  );
}

function TierTable({ data }: { readonly data: AnalyticsData }) {
  const search = currentRoute().search;
  const rows = TIER_KEYS.map((key) => ({
    key,
    share: measuredTierValue(data.autonomy!.tier.mix, key),
    band: data.autonomy!.tier.bands[key],
    count: measuredTierValue(data.kpi.by_tier, key),
  }));
  const columns: readonly Column<(typeof rows)[number]>[] = [
    {
      key: "tier",
      header: t("analytics.tier"),
      render: (row) => <a href={routeHref("trust-routing", {
        segments: [row.key],
        params: routingParamsForTier(row.key, search),
      })}>{row.key.toUpperCase()}</a>,
    },
    { key: "share", header: t("analytics.routing.share"), render: (row) => row.share === null ? t("analytics.unavailable") : formatShare(row.share), cellClass: "num" },
    { key: "band", header: t("analytics.routing.targetBand"), render: (row) => row.band ? `${Math.round(row.band[0] * 100)}-${Math.round(row.band[1] * 100)}%` : "-", cellClass: "num" },
    { key: "events", header: t("analytics.events"), render: (row) => row.count ?? t("analytics.unavailable"), cellClass: "num" },
  ];
  return <DataTable columns={columns} rows={rows} keyOf={(row) => row.key} />;
}

function EvidenceLinks({ links }: { readonly links: readonly (readonly [string, string])[] }) {
  return (
    <nav class="analytics-links" aria-label={t("analytics.relatedEvidence")}>
      {links.map(([label, href]) => <a key={href} href={href}>{label}<span aria-hidden="true">&rarr;</span></a>)}
    </nav>
  );
}
