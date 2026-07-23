import type { ComponentChildren } from "preact";
import type { AutonomyPayload, VerticalSummary } from "../types";
import { StatusPill, UnavailableState, kpiEvidenceLabel } from "../components/ui";
import { routeHref } from "../router";
import { t } from "./i18n/analytics";
import { formatUsd } from "./dashboard.model";

export type VerticalDisplayState = "measured" | "review" | "simulated" | "unavailable";

export function formatMeasuredSavings(value: number): string {
  return formatUsd(value);
}

export function verticalResolutionRate(vertical: VerticalSummary): number | null {
  return vertical.events > 0 ? vertical.auto_resolved / vertical.events : null;
}

export function verticalDisplayState(
  vertical: VerticalSummary,
  synthetic: boolean,
): VerticalDisplayState {
  if (synthetic) return "simulated";
  if (vertical.events === 0) return "unavailable";
  return vertical.open_risks > 0 ? "review" : "measured";
}

export function verticalPayloadKey(slug: string): string {
  if (slug === "change-safety") return "change_safety";
  if (slug === "cost-governance") return "cost";
  return slug;
}

export function verticalRouteSlug(payloadKey: string): string {
  if (payloadKey === "change_safety") return "change-safety";
  if (payloadKey === "cost") return "cost-governance";
  return payloadKey;
}

interface Props {
  readonly autonomy: AutonomyPayload;
  readonly active: string;
  readonly context: Readonly<Record<string, string>>;
  readonly evidence: ComponentChildren;
}

export function VerticalOutcomesBody({ autonomy, active, context, evidence }: Props) {
  const selected = autonomy.verticals.find((item) => item.key === verticalPayloadKey(active));
  if (!selected) return <UnavailableState message={t("analytics.verticals.unavailable")} />;
  return (
    <div class="vertical-outcomes stack">
      {autonomy.synthetic ? (
        <section class="vertical-boundary-banner">
          <strong>{t("analytics.verticals.simulatedTitle")}</strong>
          <span>{t("analytics.simulatedEvidenceBoundary")}</span>
        </section>
      ) : null}
      {active === "cost-governance" ? <CostReferenceNotice /> : null}
      {evidence}
      <VerticalSummaryGrid
        active={active}
        autonomy={autonomy}
        context={context}
      />
      <section class="vertical-detail-grid">
        <SelectedVerticalPanel
          autonomy={autonomy}
          context={context}
          selected={selected}
        />
        <VerticalEvidencePanel
          autonomy={autonomy}
          context={context}
          selected={selected}
        />
      </section>
      <CrossVerticalComparison
        autonomy={autonomy}
        context={context}
      />
      <nav class="analytics-links" aria-label={t("analytics.relatedEvidence")}>
        <a href={verticalIncidentsHref(selected, autonomy.synthetic, context)}>{t("analytics.viewIncidents")}</a>
        <a href={verticalAuditHref(selected, autonomy, context)}>{t("analytics.viewAudit")}</a>
      </nav>
    </div>
  );
}

function VerticalSummaryGrid({
  active,
  autonomy,
  context,
}: {
  readonly active: string;
  readonly autonomy: AutonomyPayload;
  readonly context: Readonly<Record<string, string>>;
}) {
  return (
    <section class="vertical-summary-grid" aria-label={t("analytics.verticals.summaryLabel")}>
      {autonomy.verticals.map((vertical) => {
        const slug = verticalRouteSlug(vertical.key);
        const state = verticalDisplayState(vertical, autonomy.synthetic);
        const rate = verticalResolutionRate(vertical);
        return (
          <a
            class={`vertical-summary${slug === active ? " is-active" : ""}`}
            href={routeHref("verticals", { segments: [slug], params: context })}
            aria-current={slug === active ? "page" : undefined}
            key={vertical.key}
          >
            <span class="vertical-summary-head">
              <strong>{t(`overview.vertical.${vertical.key}`)}</strong>
              <VerticalStatePill state={state} />
            </span>
            <b class={rate === null ? "is-unavailable" : undefined}>
              {rate === null ? kpiEvidenceLabel("insufficient-sample") : formatRate(rate)}
            </b>
            <small>{t("analytics.resolutionRate")}</small>
            <dl>
              <VerticalFact label={t("analytics.events")} value={vertical.events} />
              <VerticalFact label={t("analytics.autoResolved")} value={vertical.auto_resolved} />
              <VerticalFact label={t("analytics.openRisks")} value={vertical.open_risks} />
              <VerticalFact label={t("analytics.monthlySavings")} value={formatMeasuredSavings(vertical.monthly_savings)} />
            </dl>
          </a>
        );
      })}
    </section>
  );
}

function SelectedVerticalPanel({
  autonomy,
  context,
  selected,
}: {
  readonly autonomy: AutonomyPayload;
  readonly context: Readonly<Record<string, string>>;
  readonly selected: VerticalSummary;
}) {
  const rate = verticalResolutionRate(selected);
  const auditHref = verticalAuditHref(selected, autonomy, context);
  return (
    <section class="vertical-detail-panel">
      <header>
        <div>
          <h3>{t("analytics.verticals.outcomeTitle", { vertical: t(`overview.vertical.${selected.key}`) })}</h3>
          <p>{t("analytics.verticals.outcomeSubtitle")}</p>
        </div>
        <VerticalStatePill state={verticalDisplayState(selected, autonomy.synthetic)} />
      </header>
      <a class="vertical-primary-outcome" href={routeHref("audit", {
        params: { ...verticalAuditParams(selected, autonomy, context), outcome: "auto" },
      })}>
        <strong class={rate === null ? "is-unavailable" : undefined}>
          {rate === null ? kpiEvidenceLabel("insufficient-sample") : formatRate(rate)}
        </strong>
        <span>{t("analytics.resolutionRate")}</span>
      </a>
      <div class="vertical-outcome-bar" aria-hidden="true">
        <span style={{ width: `${rate === null ? 0 : rate * 100}%` }} />
      </div>
      <div class="vertical-detail-links">
        <a href={auditHref}><span>{t("analytics.events")}</span><strong>{selected.events}</strong></a>
        <a href={routeHref("audit", { params: { ...verticalAuditParams(selected, autonomy, context), outcome: "auto" } })}><span>{t("analytics.autoResolved")}</span><strong>{selected.auto_resolved}</strong></a>
      </div>
    </section>
  );
}

function VerticalEvidencePanel({
  autonomy,
  context,
  selected,
}: {
  readonly autonomy: AutonomyPayload;
  readonly context: Readonly<Record<string, string>>;
  readonly selected: VerticalSummary;
}) {
  return (
    <section class="vertical-detail-panel">
      <header>
        <div>
          <h3>{t("analytics.verticals.evidenceTitle", { vertical: t(`overview.vertical.${selected.key}`) })}</h3>
          <p>{t("analytics.verticals.evidenceSubtitle")}</p>
        </div>
      </header>
      <div class="vertical-evidence-list">
        <a href={verticalIncidentsHref(selected, autonomy.synthetic, context)}>
          <span>{t("analytics.openRisks")}</span><strong>{selected.open_risks}</strong>
        </a>
        <a href={verticalAuditHref(selected, autonomy, context)}>
          <span>{t("analytics.monthlySavings")}</span><strong>{formatMeasuredSavings(selected.monthly_savings)}</strong>
        </a>
        <a href={routeHref("verticals", { segments: [verticalRouteSlug(selected.key)], params: context })}>
          <span>{t("analytics.verticals.trendEvidence")}</span><strong class="is-unavailable">{t("analytics.unavailable")}</strong>
        </a>
        <a href={routeHref("verticals", { segments: [verticalRouteSlug(selected.key)], params: context })}>
          <span>{t("analytics.verticals.specificEvidence")}</span><strong class="is-unavailable">{t("analytics.unavailable")}</strong>
        </a>
      </div>
    </section>
  );
}

function CrossVerticalComparison({
  autonomy,
  context,
}: {
  readonly autonomy: AutonomyPayload;
  readonly context: Readonly<Record<string, string>>;
}) {
  return (
    <section class="vertical-comparison">
      <header class="vertical-comparison-head">
        <div>
          <h3>{t("analytics.verticals.comparison")}</h3>
          <p>{t("analytics.verticals.comparisonSubtitle")}</p>
        </div>
      </header>
      <div class="vertical-comparison-table" role="table" aria-label={t("analytics.verticals.comparison")}>
        <div class="vertical-comparison-row is-header" role="row">
          <span role="columnheader">{t("analytics.verticalLabel")}</span>
          <span role="columnheader">{t("analytics.events")}</span>
          <span role="columnheader">{t("analytics.autoResolved")}</span>
          <span role="columnheader">{t("analytics.resolutionRate")}</span>
          <span role="columnheader">{t("analytics.openRisks")}</span>
          <span role="columnheader">{t("analytics.monthlySavings")}</span>
        </div>
        {autonomy.verticals.map((vertical) => {
          const rate = verticalResolutionRate(vertical);
          return (
            <a
              class="vertical-comparison-row"
              href={routeHref("verticals", { segments: [verticalRouteSlug(vertical.key)], params: context })}
              role="row"
              key={vertical.key}
            >
              <strong role="cell">{t(`overview.vertical.${vertical.key}`)}</strong>
              <span role="cell">{vertical.events}</span>
              <span role="cell">{vertical.auto_resolved}</span>
              <span role="cell" class={rate === null ? "is-unavailable" : undefined}>{rate === null ? t("analytics.unavailable") : formatRate(rate)}</span>
              <span role="cell">{vertical.open_risks}</span>
              <span role="cell">{formatMeasuredSavings(vertical.monthly_savings)}</span>
            </a>
          );
        })}
      </div>
    </section>
  );
}

function CostReferenceNotice() {
  return (
    <aside class="analytics-reference-note" role="note" aria-label={t("analytics.outcomes.costNoticeLabel")}>
      <span class="analytics-reference-icon" aria-hidden="true">i</span>
      <div>
        <strong>{t("analytics.outcomes.costNoticeTitle")}</strong>
        <p>{t("analytics.outcomes.costNoticeBody")}</p>
      </div>
    </aside>
  );
}

function VerticalStatePill({ state }: { readonly state: VerticalDisplayState }) {
  const kind = state === "review" ? "warning" : state === "measured" ? "success" : "neutral";
  return <StatusPill kind={kind} label={t(`analytics.verticals.state.${state}`)} />;
}

function VerticalFact({ label, value }: { readonly label: string; readonly value: string | number }) {
  return <div><dt>{label}</dt><dd>{value}</dd></div>;
}

function verticalAuditParams(
  vertical: VerticalSummary,
  autonomy: AutonomyPayload,
  context: Readonly<Record<string, string>>,
): Readonly<Record<string, string | null>> {
  return {
    ...context,
    window: `${autonomy.window_days}d`,
    vertical: autonomy.synthetic ? null : vertical.key,
  };
}

function verticalAuditHref(
  vertical: VerticalSummary,
  autonomy: AutonomyPayload,
  context: Readonly<Record<string, string>>,
): string {
  return routeHref("audit", { params: verticalAuditParams(vertical, autonomy, context) });
}

function verticalIncidentsHref(
  vertical: VerticalSummary,
  synthetic: boolean,
  context: Readonly<Record<string, string>>,
): string {
  return routeHref("incidents", {
    params: { ...context, vertical: synthetic ? null : vertical.key },
  });
}

function formatRate(rate: number): string {
  return `${Math.round(rate * 100)}%`;
}
