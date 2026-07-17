import type { AutonomyPayload, DashboardKpi } from "../types";
import { t } from "../i18n";
import { routeHref } from "../router";
import { formatShare, type GatesSummary, type OverviewHealth } from "./dashboard.model";

export function ExecutiveDecisionGrid({
  health,
  kpi,
  gates,
  autonomy,
  attentionCount,
  policyEscapes,
}: {
  readonly health: OverviewHealth;
  readonly kpi: DashboardKpi;
  readonly gates: GatesSummary | null;
  readonly autonomy: AutonomyPayload | null;
  readonly attentionCount: number;
  readonly policyEscapes: number | null;
}) {
  const failedGuards = autonomy !== null && !autonomy.synthetic
    ? autonomy.guards.filter((guard) => !guard.ok)
    : [];
  return (
    <section class="overview-decision-grid" aria-label={t("overview.decision.label")}>
      <a href={routeHref("control-assurance")} class="overview-control-panel overview-drill-card">
        <div class="overview-panel-head">
          <div>
            <span class="overview-panel-kicker">{t("overview.assurance.label")}</span>
            <h3>{t("overview.assurance.title")}</h3>
          </div>
          <span class={`overview-control-state overview-control-state-${health}`}>
            {health === "healthy"
              ? t("overview.assurance.passing")
              : health === "attention"
                ? t("overview.assurance.blocked")
                : t("overview.evidence.unavailable")}
          </span>
        </div>
        <dl class="overview-assurance-list">
          <AssuranceRow
            label={t("overview.assurance.escapes")}
            value={
              policyEscapes === null
                ? t("overview.evidence.unavailable")
                : policyEscapes === 0
                  ? t("overview.assurance.noneRecorded")
                  : t("overview.assurance.escapeCount", { count: policyEscapes })
            }
            state={policyEscapes === null ? "unknown" : policyEscapes === 0 ? "ok" : "attention"}
          />
          <AssuranceRow
            label={t("overview.assurance.thresholds")}
            value={
              autonomy
                ? autonomy.synthetic
                  ? t("overview.evidence.simulated")
                  : t("overview.assurance.thresholdCount", {
                      failed: failedGuards.length,
                      total: autonomy.guards.length,
                    })
                : t("overview.evidence.unavailable")
            }
            state={
              autonomy === null || autonomy.synthetic
                ? "unknown"
                : failedGuards.length === 0
                  ? "ok"
                  : "attention"
            }
          />
          <AssuranceRow
            label={t("overview.assurance.shadow")}
            value={formatShare(kpi.shadow_share)}
            state={kpi.shadow_share >= 0.95 ? "ok" : "attention"}
          />
          <AssuranceRow
            label={t("overview.assurance.promotion")}
            value={
              gates
                ? t("overview.guards.ready", {
                    ready: gates.ready_count,
                    total: gates.rows.length,
                  })
                : t("overview.evidence.unavailable")
            }
            state={gates === null ? "unknown" : gates.blocked_count === 0 ? "ok" : "attention"}
          />
        </dl>
      </a>

      <div class="overview-attention-panel">
        <div class="overview-panel-head">
          <div>
            <span class="overview-panel-kicker">{t("overview.attention.label")}</span>
            <h3>
              {attentionCount > 0
                ? t("overview.attention.title", { count: attentionCount })
                : t("overview.attention.clear")}
            </h3>
          </div>
        </div>
        {attentionCount > 0 ? (
          <ul class="overview-attention-list">
            {kpi.hil_pending > 0 ? (
              <AttentionItem
                href={routeHref("hil-queue")}
                tone="critical"
                title={t("overview.attention.hilTitle", { count: kpi.hil_pending })}
                hint={t("overview.attention.hilHint")}
              />
            ) : null}
            {policyEscapes !== null && policyEscapes > 0 ? (
              <AttentionItem
                href={routeHref("promotion-gates", { params: { status: "blocked", reason: "policy-escape" } })}
                tone="critical"
                title={t("overview.attention.escapeTitle", { count: policyEscapes })}
                hint={t("overview.attention.escapeHint")}
              />
            ) : null}
            {failedGuards.map((guard) => (
              <AttentionItem
                key={guard.key}
                href={routeHref("control-assurance")}
                tone="high"
                title={t("overview.attention.guardTitle", {
                  guard: t(`overview.guard.${guard.key}`),
                })}
                hint={t("overview.attention.guardHint", {
                  value: `${(guard.value * 100).toFixed(1)}%`,
                  threshold: `${(guard.threshold * 100).toFixed(1)}%`,
                })}
              />
            ))}
          </ul>
        ) : health === "unknown" ? (
          <AttentionEmpty kind="unknown" />
        ) : (
          <AttentionEmpty kind="clear" />
        )}
      </div>
    </section>
  );
}

function AssuranceRow({
  label,
  value,
  state,
}: {
  readonly label: string;
  readonly value: string;
  readonly state: "ok" | "attention" | "unknown";
}) {
  return (
    <div>
      <dt>{label}</dt>
      <dd class={state}>{value}</dd>
    </div>
  );
}

function AttentionItem({
  href,
  tone,
  title,
  hint,
}: {
  readonly href: string;
  readonly tone: "critical" | "high";
  readonly title: string;
  readonly hint: string;
}) {
  return (
    <li>
      <a href={href}>
        <span class={`overview-attention-tone overview-attention-tone-${tone}`}>
          {t(`overview.attention.${tone}`)}
        </span>
        <span class="overview-attention-copy">
          <strong>{title}</strong>
          <span class="muted">{hint}</span>
        </span>
        <span aria-hidden="true">&rarr;</span>
      </a>
    </li>
  );
}

function AttentionEmpty({ kind }: { readonly kind: "unknown" | "clear" }) {
  return (
    <div class="overview-attention-empty">
      <strong>{t(`overview.attention.${kind}Title`)}</strong>
      <span class="muted">{t(`overview.attention.${kind}Hint`)}</span>
    </div>
  );
}
