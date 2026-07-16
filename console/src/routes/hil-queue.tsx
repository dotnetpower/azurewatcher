import { useEffect, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import type { HilQueueItem } from "../types";
import {
  AsyncBoundary,
  EmptyState,
  PageHeader,
  StatusPill,
  type AsyncState,
} from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, agentTerm, composeGlossary } from "../deck/glossary";
import { t } from "../i18n";
import { routeHref } from "../router";

interface Props {
  readonly client: ReadApiClient;
}

export function HilQueueRoute({ client }: Props) {
  const [state, setState] = useState<AsyncState<HilQueueData>>({
    status: "loading",
  });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const page = await client.listHilQueue({ limit: 100 });
        if (!cancelled) {
          setState({
            status: "ready",
            data: { items: page.items, total: page.total, detailLevel: page.detail_level },
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

  return (
    <div class="stack">
      <PageHeader
        title={t("route.hilQueue")}
        subtitle={<>{t("approvals.subtitle")}</>}
        actions={
          <StatusPill kind="neutral" label="read-only" />
        }
      />
      <AsyncBoundary state={state} resourceLabel={t("approvals.resource")}>
        {(data) => <HilBody data={data} />}
      </AsyncBoundary>
    </div>
  );
}

interface HilQueueData {
  readonly items: readonly HilQueueItem[];
  readonly total: number;
  readonly detailLevel: "full" | "count_only";
}

function HilBody({ data }: { readonly data: HilQueueData }) {
  const { items, total, detailLevel } = data;
  const truncated = total > items.length;
  usePublishViewContext(
    () => ({
      routeId: "hil-queue",
      routeLabel: "Approvals",
      purpose:
        "High-risk actions the risk gate parked for a human approver instead of " +
        "auto-executing. Read-only: approvals happen in Teams/ChatOps cards, " +
        "never a console button, and never self-approval. Each item shows the " +
        "recorded reason it needs a human.",
      glossary: composeGlossary([
        TERMS.hil,
        TERMS.actionKind,
        TERMS.gateDecision,
        TERMS.correlationId,
      ]),
      headline: total === 0
        ? t("approvals.headlineEmpty")
        : t("approvals.headlineWaiting", { count: total }),
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "pending", value: total, group: "queue" },
        { key: "displayed", value: items.length, group: "queue" },
        { key: "truncated", value: truncated, group: "queue" },
        { key: "detail_level", value: detailLevel, group: "access" },
      ],
      records: {
        items: items.map((i) => ({
          approval_id: i.approval_id,
          action_kind: i.action_kind,
          reason: i.reason,
          target_resource_ref: i.target_resource_ref,
          mode: i.mode,
          stop_condition: i.stop_condition,
          rollback_kind: i.rollback_kind,
          blast_radius_scope: i.blast_radius_scope,
          blast_radius_count: i.blast_radius_count,
          citing_rule_ids: i.citing_rule_ids,
          requested_at: i.requested_at,
          ttl_expires_at: i.ttl_expires_at,
          idempotency_key: i.idempotency_key,
          correlation_id: i.correlation_id,
        })),
      },
    }),
    [items, total, truncated, detailLevel],
  );

  if (total === 0) {
    return (
      <EmptyState
        title={t("approvals.emptyTitle")}
        body={t("approvals.emptyBody")}
      />
    );
  }

  if (detailLevel === "count_only") {
    return (
      <section class="approvals-count-only" aria-label="Pending approval count">
        <StatusPill kind="hil" label={t("approvals.pendingCount", { count: total })} />
        <div>
          <h3>{t("approvals.detailsRoleTitle")}</h3>
          <p>{t("approvals.detailsRoleBody")}</p>
        </div>
      </section>
    );
  }

  const [query, setQuery] = useState("");
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const visibleItems = normalizedQuery
    ? items.filter((item) => approvalSearchText(item).includes(normalizedQuery))
    : items;

  return (
    <div class="stack approvals-view">
      <section class="approvals-mechanics" aria-label="Approval mechanics">
        <strong>{t("approvals.mechanicsTitle")}</strong>
        <span>{t("approvals.mechanicsBody")}</span>
      </section>
      <div class="approvals-toolbar">
        <div class="approvals-summary" aria-label="Approval queue summary">
          <StatusPill kind="hil" label={t("approvals.pendingCount", { count: total })} />
          <StatusPill kind="neutral" label={t("approvals.shownCount", { count: visibleItems.length })} />
          <StatusPill kind="shadow" label={t("approvals.readOnly")} />
        </div>
        <label class="approvals-search">
          <span class="sr-only">{t("approvals.filter")}</span>
          <input
            type="search"
            value={query}
            placeholder={t("approvals.filterPlaceholder")}
            onInput={(event) => setQuery(event.currentTarget.value)}
          />
        </label>
      </div>
      {truncated ? (
        <p class="muted footnote">
          {t("approvals.showingLatest", { shown: items.length, total })}
        </p>
      ) : null}
      {visibleItems.length === 0 ? (
        <EmptyState
          title={t("approvals.noMatchTitle")}
          body={t("approvals.noMatchBody")}
        />
      ) : (
        <div class="approval-card-list">
          {visibleItems.map((item) => <ApprovalCard key={item.idempotency_key} item={item} />)}
        </div>
      )}
    </div>
  );
}

function approvalSearchText(item: HilQueueItem): string {
  return [
    item.action_kind,
    item.target_resource_ref,
    item.event_id,
    item.correlation_id,
    item.reason,
    ...item.reasons,
    ...item.citing_rule_ids,
  ].filter(Boolean).join(" ").toLocaleLowerCase();
}

function ApprovalCard({ item }: { readonly item: HilQueueItem }) {
  const expired = item.ttl_expires_at !== null &&
    new Date(item.ttl_expires_at).getTime() <= Date.now();
  const reasons = item.reasons.length > 0 ? item.reasons : [item.reason];
  const blastRadius = item.blast_radius_summary || [
    item.blast_radius_count !== null
      ? t(item.blast_radius_count === 1 ? "approvals.resourceCountOne" : "approvals.resourceCountMany", { count: item.blast_radius_count })
      : "",
    item.blast_radius_scope,
    item.blast_radius_rate_per_minute !== null
      ? t("approvals.rateCap", { count: item.blast_radius_rate_per_minute })
      : "",
  ].filter(Boolean).join(" · ");
  const rollback = [item.rollback_kind, item.rollback_reference].filter(Boolean).join(" · ");
  const facts = [
    [t("approvals.fieldApprovalId"), item.approval_id],
    [t("approvals.fieldActionId"), item.action_id],
    [t("approvals.fieldTarget"), item.target_resource_ref],
    [t("approvals.fieldBlastRadius"), blastRadius],
    [t("approvals.fieldRollback"), rollback],
    [t("approvals.fieldStopCondition"), item.stop_condition],
    [t("approvals.fieldGroundedOn"), item.citing_rule_ids.join(", ")],
  ] as const;

  return (
    <article class="approval-card">
      <div class="approval-card-body">
        <header class="approval-card-head">
          <h3>{item.action_kind}</h3>
          <StatusPill
            kind={expired ? "danger" : "hil"}
            label={expired ? t("approvals.expiredApproval") : t("approvals.pendingApproval")}
          />
          {item.mode ? (
            <StatusPill
              kind={item.mode === "enforce" ? "enforce" : "shadow"}
              label={item.mode}
            />
          ) : null}
        </header>
        <p class="approval-card-what">
          <strong>{t("approvals.what")}</strong>{" "}
          {item.target_resource_ref
            ? t("approvals.applyTarget", { action: item.action_kind, target: item.target_resource_ref })
            : t("approvals.applyRecorded", { action: item.action_kind })}
        </p>
        <div class="approval-card-why">
          <strong>{t("approvals.why")}</strong>
          <ul>{reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
        </div>
        <dl class="approval-facts">
          {facts.map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>
                {label === t("approvals.fieldGroundedOn") && item.citing_rule_ids.length > 0 ? (
                  <span class="approval-rule-links">
                    {item.citing_rule_ids.map((ruleId) => (
                      <a key={ruleId} href={routeHref("rules", { params: { rule: ruleId } })}>
                        {ruleId}
                      </a>
                    ))}
                  </span>
                ) : value || <span class="muted">{t("approvals.notRecorded")}</span>}
              </dd>
            </div>
          ))}
        </dl>
        <footer class="approval-card-foot">
          <span>{t("approvals.requested", { timestamp: item.requested_at })}</span>
          {item.ttl_expires_at ? (
            <span>{t("approvals.expires", { timestamp: item.ttl_expires_at })}</span>
          ) : <span class="muted">{t("approvals.ttlNotRecorded")}</span>}
          <code>{item.event_id}</code>
          {item.correlation_id ? <code>{item.correlation_id}</code> : null}
        </footer>
        {item.correlation_id ? (
          <nav class="approval-card-actions" aria-label={t("approvals.relatedEvidence")}>
            <a href={routeHref("incidents", { params: { status: "all", correlation: item.correlation_id } })}>
              {t("approvals.openIncident")}
            </a>
            <a href={routeHref("trace", { params: { correlation: item.correlation_id } })}>
              {t("approvals.openTrace")}
            </a>
            <a href={routeHref("audit", { params: { correlation: item.correlation_id } })}>
              {t("approvals.openAudit")}
            </a>
            <a href={routeHref("rca", { params: { correlation: item.correlation_id } })}>
              {t("approvals.openRca")}
            </a>
          </nav>
        ) : null}
      </div>
    </article>
  );
}
