import { currentRoute, replaceRouteState, routeHref } from "../router";
/**
 * Live cockpit route.
 *
 * Renders control-plane stage events streamed over SSE (`GET /live/stream`)
 * as an activity swarm. Design goals:
 *
 * - **Fixed slot pool** - tiles never shift position. New events fade in
 *   at their assigned slot; existing tiles transition smoothly in place.
 * - **Information hierarchy** - the ActionType is the headline of each
 *   tile; tier / gate / age are quiet annotations. HIL and deny tiles
 *   visually pop (rim glow, badge, subtle scale).
 * - **Status-local color** - vertical, tier, and gate colors stay on
 *   chips, badges, dots, and whole-surface tints; tile edges stay neutral.
 * - **Stage progress** - six dots at the top of each tile fill in as the
 *   pipeline advances. A T2 event that spends time in `verify` is
 *   visible without leaving text.
 * - **Filters** - a top-of-page chipset dims everything except the
 *   selected outcome. Non-matching tiles fade to 15% opacity.
 * - **Detail panel** - clicking a tile slides a read-only side panel
 *   with the full event payload the server sent (rule / action /
 *   verifier passes / etc.).
 * - **Sparkline + guard status** - the KPI strip shows a 60s events/sec
 *   sparkline and four traffic-light guards (CFR / FPR / rollback /
 *   escapes) sourced from the audit ticker.
 *
 * The route is pure read-only: it never issues privileged calls, and
 * every fan-out primitive it uses ({@link useLiveStream}) is a
 * translator, never a judge.
 */

import { useEffect, useMemo, useReducer, useRef, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import { loadConfig } from "../config";
import type { LiveStageEvent } from "../hooks/use-live-stream";
import { useLiveStream } from "../hooks/use-live-stream";
import { observationSourceLabel } from "../hooks/observation-source";
import { t } from "./i18n/live";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import {
  POOL_SIZE,
  RATE_WINDOW_MS,
  formatDuration,
  formatAge,
  isTileStuck,
  liveSelectionState,
  makeInitialState,
  reducer,
  shortTime,
  sumBuckets,
  type FilterKind,
  type TileState,
} from "./live.model";
import { DetailPanel, LiveQueue, LiveTile, Sparkline, StackBar } from "./live.tiles";

interface Props {
  readonly client: ReadApiClient;
}

function decisionLabel(decision: string): string {
  const key = `live.decision.${decision}`;
  const label = t(key);
  return label === key ? decision : label;
}

export function liveTraceHref(correlationId: string): string {
  return routeHref("trace", { params: { correlation: correlationId } });
}

export function LiveRoute({ client }: Props) {
  const initialRoute = currentRoute();
  const [state, dispatch] = useReducer(reducer, undefined, makeInitialState);
  const [tickerPaused, setTickerPaused] = useState(false);
  const [tickerCollapsed, setTickerCollapsed] = useState(false);
  const [viewMode, setViewMode] = useState<"queue" | "flow">(
    initialRoute.search.get("view") === "flow" ? "flow" : "queue",
  );
  const [frozenObserved, setFrozenObserved] = useState(0);
  const pausedSnapshotRef = useRef<readonly LiveStageEvent[]>([]);
  const pausedRef = useRef(false);
  const frozenObservedRef = useRef(0);
  const pendingEventsRef = useRef<LiveStageEvent[]>([]);

  const updateRoute = ({
    eventId = state.selectedEventId,
    filter = state.filter,
    view = viewMode,
  }: {
    readonly eventId?: string | null;
    readonly filter?: FilterKind;
    readonly view?: "queue" | "flow";
  }): void => {
    dispatch({ kind: "filter", value: filter });
    setViewMode(view);
    replaceRouteState(routeHref("live", {
      params: {
        event: eventId,
        filter: filter === "all" ? null : filter,
        view: view === "queue" ? null : view,
      },
    }));
  };

  const selectEvent = (eventId: string | null): void => {
    dispatch({ kind: "select", event_id: eventId });
    replaceRouteState(routeHref("live", {
      params: {
        event: eventId,
        filter: state.filter === "all" ? null : state.filter,
        view: viewMode === "queue" ? null : viewMode,
      },
    }));
  };

  useEffect(() => {
    const sync = () => {
      const route = currentRoute();
      const filter = route.search.get("filter");
      dispatch({
        kind: "filter",
        value: filter === "hil" || filter === "deny" || filter === "failed" || filter === "stuck"
          ? filter
          : "all",
      });
      dispatch({ kind: "select", event_id: route.search.get("event") });
      setViewMode(route.search.get("view") === "flow" ? "flow" : "queue");
    };
    sync();
    window.addEventListener("popstate", sync);
    window.addEventListener("fdai:route-changed", sync);
    return () => {
      window.removeEventListener("popstate", sync);
      window.removeEventListener("fdai:route-changed", sync);
    };
  }, []);

  const url = useMemo(() => {
    const cfg = loadConfig();
    const base = cfg.readApiBaseUrl || (typeof window !== "undefined" ? window.location.origin : "");
    return `${base.replace(/\/$/, "")}/live/stream`;
  }, []);

  const { status, lastError, source: streamSource } = useLiveStream({
    url,
    getAuthorizationHeader: client.authorizationHeader,
    onEvent: (event) => {
      // Buffer events; the setInterval flusher below folds them into
      // ONE reducer dispatch per tick so a high-rate stream never
      // triggers one React render per event (that path OOMs the
      // browser after a few minutes on tabs left open).
      if (pausedRef.current) {
        frozenObservedRef.current += 1;
        return;
      }
      pendingEventsRef.current.push(event);
    },
  });

  // Buffer + interval flusher for the SSE stream. Bounded at
  // FLUSH_CAP so a tab that was in the background does not drain a
  // huge backlog into one dispatch when it becomes visible. Uses
  // setInterval (not requestAnimationFrame) so the flusher does NOT
  // fire at 60 Hz when the buffer is empty - the reducer only runs
  // when there is real work.
  useEffect(() => {
    const FLUSH_CAP = 200;
    const FLUSH_INTERVAL_MS = 250;
    const handle = window.setInterval(() => {
      if (pausedRef.current) {
        setFrozenObserved(frozenObservedRef.current);
        return;
      }
      const buffer = pendingEventsRef.current;
      if (buffer.length === 0) return;
      const drained =
        buffer.length > FLUSH_CAP ? buffer.slice(-FLUSH_CAP) : buffer.slice();
      pendingEventsRef.current = [];
      dispatch({ kind: "batch", events: drained });
    }, FLUSH_INTERVAL_MS);
    return () => {
      window.clearInterval(handle);
      pendingEventsRef.current = [];
    };
  }, []);

  useEffect(() => {
    const handle = window.setInterval(() => {
      if (pausedRef.current) return;
      dispatch({ kind: "tick", now: Date.now() });
    }, 250);
    return () => window.clearInterval(handle);
  }, []);

  // Pause freezes the full presentation while leaving the read-only SSE
  // connection open. Frames received during the pause are intentionally
  // ignored; History remains the source for complete recorded outcomes.
  const displayedTicker = tickerPaused ? pausedSnapshotRef.current : state.ticker;

  const togglePause = () => {
    if (tickerPaused) {
      pausedRef.current = false;
      setTickerPaused(false);
      pausedSnapshotRef.current = [];
    } else {
      pausedRef.current = true;
      frozenObservedRef.current = 0;
      setFrozenObserved(0);
      pendingEventsRef.current = [];
      pausedSnapshotRef.current = state.ticker;
      setTickerPaused(true);
    }
  };
  const toggleCollapse = () => setTickerCollapsed((v) => !v);

  const selectedTile = state.selectedEventId
    ? state.tiles.find((t) => t?.event_id === state.selectedEventId) ?? null
    : null;
  const selectionState = liveSelectionState(
    state.selectedEventId,
    selectedTile,
    state.session_total,
  );

  const eps = (state.ratePings.length / (RATE_WINDOW_MS / 1000)).toFixed(1);
  const gateTotal = Object.values(state.gateCounts).reduce((a, b) => a + b, 0);
  const tierTotal = Object.values(state.tierCounts).reduce((a, b) => a + b, 0);
  const autoShare = gateTotal > 0 ? Math.round(((state.gateCounts.auto ?? 0) / gateTotal) * 100) : 0;

  // Attention triage uses the backend-supplied latency budget. Missing
  // budgets never become a guessed "stuck" state in the browser.
  const attention = state.tiles.reduce(
    (acc, tile) => {
      if (!tile) return acc;
      if (tile.gate_decision === "hil") acc.hil += 1;
      if (tile.gate_decision === "deny") acc.deny += 1;
      if (tile.failed) acc.failed += 1;
      if (isTileStuck(tile, state.now)) acc.stuck += 1;
      return acc;
    },
    { hil: 0, deny: 0, failed: 0, stuck: 0 },
  );
  const attentionTotal = attention.hil + attention.deny + attention.failed + attention.stuck;

  // Environment / mode indicator. Dev mode is a session flag from config
  // - never fabricate a customer-facing environment value here.

  // Publish a rich view snapshot to the CommandDeck so the operator
  // can ask "what am I looking at?" and get grounded answers.
  const verticalCounts = useMemo(() => {
    const acc: Record<string, number> = { change: 0, resilience: 0, cost: 0, unknown: 0 };
    for (const t of state.tiles) {
      if (!t) continue;
      const v = t.vertical ?? "unknown";
      acc[v] = (acc[v] ?? 0) + 1;
    }
    return acc;
  }, [state.tiles]);
  const shadowCount = useMemo(
    () => state.tiles.filter((t) => t?.mode === "shadow").length,
    [state.tiles],
  );
  const activeTileCount = useMemo(
    () => state.tiles.filter((t) => t !== null).length,
    [state.tiles],
  );
  const filterCounts = useMemo(
    () => ({
      all: activeTileCount,
      hil: state.tiles.filter((tile) => tile?.gate_decision === "hil").length,
      deny: state.tiles.filter((tile) => tile?.gate_decision === "deny").length,
      failed: state.tiles.filter((tile) => tile?.failed === true).length,
      stuck: state.tiles.filter((tile) => tile && isTileStuck(tile, state.now)).length,
    }),
    [activeTileCount, state.now, state.tiles],
  );
  const populatedTiles = useMemo(
    () => state.tiles.filter((tile): tile is TileState => tile !== null),
    [state.tiles],
  );
  const lastEventAt = populatedTiles.reduce(
    (latest, tile) => Math.max(latest, tile.last_seen_at),
    0,
  );
  const lastEventLabel = lastEventAt > 0
    ? t("live.spark.secondsAgo", { count: Math.max(0, Math.floor((state.now - lastEventAt) / 1000)) })
    : t("live.health.notObserved");
  const streamOpen = status === "open";
  const emptyState = streamOpen
    ? t("live.empty.connected")
    : status === "connecting"
      ? t("live.empty.connecting")
      : status === "idle"
        ? t("live.empty.idle")
        : t("live.empty.unavailable");

  usePublishViewContext(
    () => {
      const pct = (v: number, total: number) =>
        total === 0 ? "0%" : `${Math.round((v / total) * 100)}%`;
      const stuckSet = new Set<string>();
      for (const t of state.tiles) {
        if (!t) continue;
        if (isTileStuck(t, state.now)) stuckSet.add(t.event_id);
      }
      return {
        routeId: "live",
        routeLabel: "Live cockpit",
        purpose:
          "The real-time cockpit: events flowing through the trust router and " +
          "risk gate right now, one tile per in-flight action, with the T0/T1/T2 " +
          "tier mix and auto/hil/deny gate mix over a rolling 60s window. " +
          "Read-only; streaming is presentation, never a judgment.",
        glossary: composeGlossary([
          TERMS.tier,
          TERMS.gateDecision,
          TERMS.mode,
          TERMS.actionKind,
          TERMS.shadowMode,
        ]),
        headline: `${activeTileCount} tile(s), ${eps} eps, ${attentionTotal} needing attention`,
        capturedAt: new Date().toISOString(),
        facts: [
          { key: "eps", value: eps, group: "throughput" },
          { key: "session.total", value: state.session_total, group: "throughput" },
          {
            key: "session.duration",
            value: formatDuration(state.now - state.session_started_at),
            group: "throughput",
          },
          { key: "tiles.active", value: activeTileCount, group: "tiles" },
          { key: "tiles.empty", value: POOL_SIZE - activeTileCount, group: "tiles" },
          { key: "tiles.shadow", value: shadowCount, group: "tiles" },
          { key: "tier.t0", value: pct(state.tierCounts.t0 ?? 0, tierTotal), group: "tier" },
          { key: "tier.t1", value: pct(state.tierCounts.t1 ?? 0, tierTotal), group: "tier" },
          { key: "tier.t2", value: pct(state.tierCounts.t2 ?? 0, tierTotal), group: "tier" },
          { key: "gate.auto", value: pct(state.gateCounts.auto ?? 0, gateTotal), group: "gate" },
          { key: "gate.hil", value: pct(state.gateCounts.hil ?? 0, gateTotal), group: "gate" },
          { key: "gate.abstain", value: pct(state.gateCounts.abstain ?? 0, gateTotal), group: "gate" },
          { key: "gate.deny", value: pct(state.gateCounts.deny ?? 0, gateTotal), group: "gate" },
          { key: "attention.total", value: attentionTotal, group: "attention" },
          { key: "attention.hil", value: attention.hil, group: "attention" },
          { key: "attention.deny", value: attention.deny, group: "attention" },
          { key: "attention.failed", value: attention.failed, group: "attention" },
          { key: "attention.stuck", value: attention.stuck, group: "attention" },
          { key: "verticals.change", value: verticalCounts.change ?? 0, group: "verticals" },
          { key: "verticals.resilience", value: verticalCounts.resilience ?? 0, group: "verticals" },
          { key: "verticals.cost", value: verticalCounts.cost ?? 0, group: "verticals" },
          { key: "verticals.unknown", value: verticalCounts.unknown ?? 0, group: "verticals" },
          // The active outcome filter and the currently selected tile, so the
          // deck can answer "what is this tile / why is it failed?" after a
          // click and knows which subset the operator is looking at. Every
          // tile's full detail is already in records.tiles for cross-lookup.
          { key: "view.filter", value: state.filter, group: "view" },
          { key: "selected_event", value: state.selectedEventId ?? "(none)", group: "selection" },
          ...(selectedTile
            ? [
                { key: "selected_action_type", value: selectedTile.action_type ?? "(none)", group: "selection" },
                { key: "selected_tier", value: selectedTile.tier ?? "(none)", group: "selection" },
                { key: "selected_gate", value: selectedTile.gate_decision ?? "(none)", group: "selection" },
                { key: "selected_vertical", value: selectedTile.vertical ?? "unknown", group: "selection" },
                { key: "selected_rule", value: selectedTile.rule ?? "(none)", group: "selection" },
                {
                  key: "selected_status",
                  value: selectedTile.failed
                    ? "failed"
                    : selectedTile.completed
                      ? "completed"
                      : "in-progress",
                  group: "selection",
                },
              ]
            : []),
        ],
        records: {
          tiles: state.tiles
            .filter((t): t is TileState => t !== null)
            .map((t) => ({
              event_id: t.event_id,
              correlation_id: t.correlation_id,
              action_type: t.action_type ?? null,
              action_types: [...t.action_types],
              rule: t.rule ?? null,
              tier: t.tier ?? null,
              mode: t.mode ?? null,
              gate_decision: t.gate_decision ?? null,
              vertical: t.vertical ?? "unknown",
              resource_type: t.resource_type ?? null,
              scope: t.scope ?? null,
              stages_completed: [...t.stages_completed],
              completed: t.completed,
              failed: t.failed,
              stuck: stuckSet.has(t.event_id),
              age_ms: state.now - t.first_seen_at,
            })),
        },
      };
    },
    [
      state.tiles,
      // state.now intentionally omitted: the deck snapshot is a
      // low-frequency projection (chat context, not live UI). Including
      // it here rebuilds the ~60-tile snapshot 4x/sec regardless of
      // real event flow, which pins CPU + GC pressure on tabs left
      // open for hours. Every real state change already comes through
      // state.tiles / state.tierCounts / state.gateCounts.
      state.tierCounts,
      state.gateCounts,
      state.session_total,
      state.session_started_at,
      eps,
      gateTotal,
      tierTotal,
      attentionTotal,
      attention.hil,
      attention.deny,
      attention.failed,
      attention.stuck,
      verticalCounts,
      shadowCount,
      activeTileCount,
      state.filter,
      state.selectedEventId,
      selectedTile,
    ],
  );

  // Keyboard shortcuts: ESC closes the detail panel, `p` toggles freeze,
  // `1..5` cycles the filter chips. All shortcuts are inert while the
  // focus is inside an input/textarea so they never steal typing.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      const tag = target?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || target?.isContentEditable) return;
      if (target?.closest('[role="dialog"]')) return;
      if (e.key === "Escape" && state.selectedEventId) {
        selectEvent(null);
        e.preventDefault();
        return;
      }
      if (e.key === "p" || e.key === "P") {
        togglePause();
        e.preventDefault();
        return;
      }
      const idx = ["1", "2", "3", "4", "5"].indexOf(e.key);
      if (idx >= 0) {
        const filters: readonly FilterKind[] = ["all", "hil", "deny", "failed", "stuck"];
        const value = filters[idx];
        if (value !== undefined) {
          updateRoute({ filter: value });
          e.preventDefault();
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [state.selectedEventId, state.filter, tickerPaused, state.session_total, state.ticker, viewMode]);

  return (
    <div class="live" data-filter={state.filter} data-ticker-collapsed={tickerCollapsed ? "1" : "0"}>
      <section class="live-header">
        <div>
          <span class="live-eyebrow">{t("live.eyebrow")}</span>
          <h2>
            {t("live.title")}
            <span class={`live-heartbeat ${streamOpen ? "is-live" : ""}`} aria-hidden="true" />
          </h2>
        </div>
        <div class="live-header-right">
          <button
            type="button"
            class="live-control-btn"
            onClick={togglePause}
            aria-pressed={tickerPaused}
            title={tickerPaused ? t("live.resumeTitle") : t("live.freezeTitle")}
          >
            {tickerPaused ? (
              <svg viewBox="0 0 12 12" width="12" height="12" aria-hidden="true">
                <path d="M3 2 L10 6 L3 10 Z" fill="currentColor" />
              </svg>
            ) : (
              <svg viewBox="0 0 12 12" width="12" height="12" aria-hidden="true">
                <rect x="3" y="2" width="2.5" height="8" fill="currentColor" />
                <rect x="6.5" y="2" width="2.5" height="8" fill="currentColor" />
              </svg>
            )}
            {tickerPaused ? t("live.resume") : t("live.freeze")}
          </button>
          <span class="live-env-badge" title={observationSourceLabel(streamSource)}>
            {observationSourceLabel(streamSource)}
          </span>
          <span class="live-context-tag">
            {t("live.context.source")} <code>GET /live/stream</code>
          </span>
          <span class="live-context-tag">
            {t("live.context.window")} <strong>60s</strong>
          </span>
          <div class={`live-status live-status-${status}`}>
            <span class="live-status-dot" />
            <span>{t(`live.status.${status === "open" ? "open" : status}`)}</span>
            {lastError ? <span class="muted"> · {lastError}</span> : null}
          </div>
        </div>
      </section>

      <p class="live-lead">
        {t("live.lead")}
      </p>

      <section class="live-health" aria-label={t("live.health.label")}>
        <div>
          <span>{t("live.health.stream")}</span>
          <strong class={`live-health-${streamOpen ? "ok" : "warn"}`}>{t(`live.status.${status === "open" ? "open" : status}`)}</strong>
        </div>
        <div>
          <span>{t("live.health.lastEvent")}</span>
          <strong>{lastEventLabel}</strong>
        </div>
        <div>
          <span>{t("live.health.environment")}</span>
          <strong>{observationSourceLabel(streamSource)}</strong>
        </div>
        <div>
          <span>{t("live.health.presentation")}</span>
          <strong>{tickerPaused ? t("live.health.frozen", { count: frozenObserved }) : t("live.health.following")}</strong>
        </div>
      </section>

      <section
        class={`live-attention ${streamOpen && attentionTotal > 0 ? "live-attention-active" : streamOpen ? "live-attention-calm" : "live-attention-unavailable"}`}
        aria-label={t("live.attention.ariaLabel")}
      >
        {streamOpen && attentionTotal > 0 ? (
          <>
            <span class="live-attention-label">{t("live.attention.label")}</span>
            {attention.hil > 0 ? (
              <button
                type="button"
                class="live-attention-chip live-attention-hil"
                onClick={() => updateRoute({ filter: "hil" })}
                title={t("live.attention.approvalTitle")}
              >
                {t("live.attention.approvals", { count: attention.hil })}
              </button>
            ) : null}
            {attention.deny > 0 ? (
              <button
                type="button"
                class="live-attention-chip live-attention-deny"
                onClick={() => updateRoute({ filter: "deny" })}
                title={t("live.attention.deniedTitle")}
              >
                {t("live.attention.denied", { count: attention.deny })}
              </button>
            ) : null}
            {attention.failed > 0 ? (
              <button
                type="button"
                class="live-attention-chip live-attention-failed"
                onClick={() => updateRoute({ filter: "failed" })}
                title={t("live.attention.failedTitle")}
              >
                {t("live.attention.failed", { count: attention.failed })}
              </button>
            ) : null}
            {attention.stuck > 0 ? (
              <button
                type="button"
                class="live-attention-chip live-attention-stuck"
                onClick={() => updateRoute({ filter: "stuck" })}
                title={t("live.attention.stuckTitle")}
              >
                {t("live.attention.stuck", { count: attention.stuck })}
              </button>
            ) : null}
            {attention.hil > 0 ? <a href={routeHref("hil-queue")}>{t("live.attention.openApprovals")}</a> : null}
          </>
        ) : (
          <span class="live-attention-calm-text">
            <i class={`live-attention-dot ${streamOpen ? "" : "unavailable"}`} />
            {streamOpen ? t("live.attention.none") : t("live.attention.unavailable")}
          </span>
        )}
      </section>

      <section class="grid live-kpis">
        <div class="card kpi live-kpi live-kpi-eps">
          <span class="label">{t("live.kpi.events")}</span>
          <span class="live-kpi-value">
            {eps}<small>{t("live.kpi.average")}</small>
          </span>
          <Sparkline buckets={state.rateBuckets} latSum={state.latSum} latCount={state.latCount} />
          <div class="live-spark-legend" aria-hidden="true">
            <span class="live-spark-key t0"><i />T0 <b>{sumBuckets(state.rateBuckets.t0)}</b></span>
            <span class="live-spark-key t1"><i />T1 <b>{sumBuckets(state.rateBuckets.t1)}</b></span>
            <span class="live-spark-key t2"><i />T2 <b>{sumBuckets(state.rateBuckets.t2)}</b></span>
          </div>
        </div>
        <div class="card kpi live-kpi">
          <span class="label">{t("live.kpi.gateMix")}</span>
          <span class="live-kpi-value">
            {autoShare}% <small>{t("live.kpi.auto")}</small>
          </span>
          <StackBar
            entries={(["auto", "hil", "abstain", "deny"] as const).map((k) => ({
              key: k,
              label: t(`live.decision.${k}`),
              value: state.gateCounts[k] ?? 0,
              className: `live-gate live-gate-${k}`,
            }))}
            total={gateTotal}
            showLegend={false}
          />
          <div class="live-mix-legend">
            {(["auto", "hil", "abstain", "deny"] as const).map((key) => (
              <span key={key} class={`live-mix-key ${key}`}>
                <i />{t(`live.decision.${key}`)} <b>{state.gateCounts[key] ?? 0}</b>
              </span>
            ))}
          </div>
        </div>
        <div class="card kpi live-kpi">
          <span class="label">{t("live.kpi.tierMix")}</span>
          <div class="live-tier-summary">
            {(["t0", "t1", "t2"] as const).map((key) => (
              <span key={key} class={`live-tier live-tier-${key}`}>
                {key.toUpperCase()} {tierTotal > 0 ? Math.round(((state.tierCounts[key] ?? 0) / tierTotal) * 100) : 0}%
              </span>
            ))}
          </div>
          <StackBar
            entries={(["t0", "t1", "t2"] as const).map((k) => ({
              key: k,
              label: k.toUpperCase(),
              value: state.tierCounts[k] ?? 0,
              className: `live-tier live-tier-${k}`,
            }))}
            total={tierTotal}
            showLegend={false}
          />
        </div>
      </section>

      <section class="live-work-header">
        <div>
          <span class="live-eyebrow">{t("live.work.eyebrow")}</span>
          <h3>{t("live.work.title")}</h3>
        </div>
        <div class="segmented-control" role="group" aria-label={t("live.work.viewModeLabel")}>
          {(["queue", "flow"] as const).map((mode) => (
            <button type="button" class={viewMode === mode ? "active" : undefined} aria-pressed={viewMode === mode} onClick={() => updateRoute({ view: mode })}>
              {mode === "queue" ? t("live.work.queue") : t("live.work.flow")}
            </button>
          ))}
        </div>
      </section>

      <section class="live-filterbar" aria-label={t("live.work.filtersLabel")}>
        {(["all", "hil", "deny", "failed", "stuck"] as const).map((f, i) => (
          <button
            key={f}
            type="button"
            class={`live-filter-chip ${state.filter === f ? "active" : ""}`}
            onClick={() => updateRoute({ filter: f })}
            title={t("live.work.filterTitle", { filter: t(`live.filter.${f}`), key: i + 1 })}
            aria-keyshortcuts={`${i + 1}`}
          >
            {t(`live.filter.${f}`)}
            <span class="live-filter-count">{filterCounts[f]}</span>
          </button>
        ))}
        <span class="muted live-filterbar-note">{t("live.work.filterNote")}</span>
      </section>

      {viewMode === "queue" ? (
        <section aria-label={t("live.work.queueLabel")}>
          <LiveQueue
            tiles={populatedTiles}
            filter={state.filter}
            selectedEventId={state.selectedEventId}
            now={state.now}
            onSelect={selectEvent}
          />
        </section>
      ) : (
      <section class="live-swarm" aria-label={t("live.work.flowLabel")}>
        {activeTileCount === 0 ? (
          <div class="live-swarm-empty" role="status">
            <strong>{streamOpen ? t("live.empty.connectedTitle") : t("live.empty.disconnectedTitle")}</strong>
            <span>{emptyState}</span>
          </div>
        ) : null}
        {state.tiles.map((tile, idx) => (
          <LiveTile
            key={idx}
            tile={tile}
            filter={state.filter}
            selected={tile?.event_id === state.selectedEventId}
            now={state.now}
            onClick={
              tile
                ? () =>
                    selectEvent(tile.event_id === state.selectedEventId ? null : tile.event_id)
                : undefined
            }
          />
        ))}
      </section>
      )}

      <aside
        class={`live-ticker card${tickerCollapsed ? " live-ticker-collapsed" : ""}${tickerPaused ? " live-ticker-paused" : ""}`}
        aria-label={t("live.outcomes.ariaLabel")}
      >
        <header class="live-ticker-header">
          <h3>
            {t("live.outcomes.title")} <span class="muted">- {t("live.outcomes.count", { count: displayedTicker.length })}</span>
          </h3>
          <div class="live-ticker-controls" role="toolbar" aria-label={t("live.outcomes.toolbarLabel")}>
            <button
              type="button"
              class="live-ticker-btn"
              onClick={toggleCollapse}
              aria-expanded={!tickerCollapsed}
              title={tickerCollapsed ? t("live.outcomes.expand") : t("live.outcomes.collapse")}
              aria-label={tickerCollapsed ? t("live.outcomes.expand") : t("live.outcomes.collapse")}
            >
              {tickerCollapsed ? (
                // chevron up (expand → show content upward)
                <svg viewBox="0 0 12 12" width="12" height="12" aria-hidden="true">
                  <path
                    d="M2 8 L6 4 L10 8"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.6"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                  />
                </svg>
              ) : (
                // chevron down (collapse)
                <svg viewBox="0 0 12 12" width="12" height="12" aria-hidden="true">
                  <path
                    d="M2 4 L6 8 L10 4"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.6"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                  />
                </svg>
              )}
            </button>
          </div>
        </header>
        {tickerCollapsed ? null : (
          <ol>
            {displayedTicker.map((evt, i) => {
              const tier = (evt.detail?.tier as string | undefined) ?? "abstain";
              const gate = evt.detail?.gate_decision as string | undefined;
              const rule = evt.detail?.rule as string | undefined;
              const action = evt.detail?.action_type as string | undefined;
              const scope = evt.detail?.scope as string | undefined;
              const outcome = evt.detail?.outcome as string | undefined;
              return (
                <li key={`${evt.event_id}-${evt.stage}-${evt.phase}-${evt.ts}-${i}`}>
                  <span class="muted">{shortTime(evt.ts)}</span>
                  <span class={`live-tier live-tier-${tier}`}>
                    {tier === "abstain" ? "N/A" : tier.toUpperCase()}
                  </span>
                  <a href={liveTraceHref(evt.correlation_id)} title={evt.correlation_id}>
                    <code>{evt.event_id.slice(0, 8)}</code>
                  </a>
                  {action ? <strong>{action}</strong> : null}
                  {scope ? <span class="live-ticker-scope">@{scope}</span> : null}
                  {rule && rule !== action ? <span class="muted">({rule})</span> : null}
                  {gate ? <span class={`live-gate live-gate-${gate}`}>{decisionLabel(gate)}</span> : null}
                  {outcome && outcome !== gate ? (
                    <span class={`live-ticker-tail ${outcome}`}>{outcome}</span>
                  ) : null}
                </li>
              );
            })}
            {displayedTicker.length === 0 ? (
              <li class="muted">{t("live.outcomes.waiting")}</li>
            ) : null}
          </ol>
        )}
        <footer class="live-ticker-footer">
          <a href={routeHref("audit")}>{t("live.outcomes.viewAll")}</a>
        </footer>
      </aside>

      {selectionState === "waiting" && state.selectedEventId ? (
        <div class="state-block state-unavailable" role="status">
          {t("live.selectionWaiting", { event: state.selectedEventId })}
        </div>
      ) : selectionState === "unavailable" && state.selectedEventId ? (
        <div class="state-block state-unavailable" role="alert">
          <span>{t("live.selectionUnavailable", { event: state.selectedEventId })}</span>
          <a href={routeHref("audit")}>{t("live.selectionOpenAudit")}</a>
        </div>
      ) : null}

      {selectedTile ? (
        <DetailPanel
          tile={selectedTile}
          now={state.now}
          onClose={() => selectEvent(null)}
        />
      ) : null}
    </div>
  );
}
