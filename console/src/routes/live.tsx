/**
 * Live cockpit route.
 *
 * Subscribes to the read-API SSE stream via {@link useLiveStream} and
 * renders three things:
 *
 * 1. **KPI strip** - events / sec, tier mix, gate-decision mix,
 *    connection status. All derived from the rolling window kept in
 *    component state.
 * 2. **Activity swarm** - one tile per recent event. Tier drives the
 *    left rail colour; the last completed gate decision drives the
 *    top-edge stamp; failed executes glow red.
 * 3. **Audit ticker** - the last few stage frames as text lines.
 *
 * Backpressure is handled by capping the in-memory buffers and dropping
 * the oldest entries. The route never blocks the render loop on the
 * SSE consumer.
 */

import { useEffect, useMemo, useReducer, useRef } from "preact/hooks";
import type { ReadApiClient } from "../api";
import { loadConfig } from "../config";
import type {
  LiveConnectionStatus,
  LiveStageEvent,
  LiveStageName,
  LiveStagePhase,
} from "../hooks/use-live-stream";
import { useLiveStream } from "../hooks/use-live-stream";

interface Props {
  readonly client: ReadApiClient;
}

// ---------------------------------------------------------------------------
// State: a fixed-size ring of recent stage events, indexed for the tile view
// ---------------------------------------------------------------------------

const TILE_CAP = 84;
const TICKER_CAP = 8;
const RATE_WINDOW_MS = 60_000;

interface TileState {
  readonly event_id: string;
  readonly tier: string | undefined;
  readonly rule: string | undefined;
  readonly action_type: string | undefined;
  readonly scope: string | undefined;
  readonly vertical: string | undefined;
  readonly current_stage: LiveStageName;
  readonly phase: LiveStagePhase;
  readonly gate_decision: string | undefined;
  readonly outcome: string | undefined;
  readonly failed: boolean;
  readonly updated_at: number;
}

interface LiveState {
  readonly tiles: readonly TileState[];
  readonly ticker: readonly LiveStageEvent[];
  /** Rolling window of `{stage=audit phase=done ts=<ms>}` timestamps used
   *  for the events/sec KPI. */
  readonly ratePings: readonly number[];
  readonly tierCounts: Readonly<Record<string, number>>;
  readonly gateCounts: Readonly<Record<string, number>>;
}

const initialState: LiveState = {
  tiles: [],
  ticker: [],
  ratePings: [],
  tierCounts: {},
  gateCounts: {},
};

type Action =
  | { readonly kind: "event"; readonly event: LiveStageEvent }
  | { readonly kind: "tick"; readonly now: number };

function reducer(state: LiveState, action: Action): LiveState {
  if (action.kind === "tick") {
    // Drop rate pings that fell out of the window.
    const cutoff = action.now - RATE_WINDOW_MS;
    const pings = state.ratePings.filter((t) => t >= cutoff);
    if (pings.length === state.ratePings.length) return state;
    return { ...state, ratePings: pings };
  }

  const evt = action.event;
  const detail = evt.detail ?? {};
  const now = Date.now();
  const tier = pickString(detail, "tier") ?? pickString(detail, "routed_to");
  const rule = pickString(detail, "rule");
  const actionType = pickString(detail, "action_type");
  const scope = pickString(detail, "scope");
  const vertical = pickString(detail, "vertical");
  const gateDecision = pickString(detail, "gate_decision");
  const outcome = pickString(detail, "outcome");

  const existingIdx = state.tiles.findIndex((t) => t.event_id === evt.event_id);
  const previous = existingIdx >= 0 ? state.tiles[existingIdx] : undefined;
  const next: TileState = {
    event_id: evt.event_id,
    tier: tier ?? previous?.tier,
    rule: rule ?? previous?.rule,
    action_type: actionType ?? previous?.action_type,
    scope: scope ?? previous?.scope,
    vertical: vertical ?? previous?.vertical,
    current_stage: evt.stage,
    phase: evt.phase,
    gate_decision: gateDecision ?? previous?.gate_decision,
    outcome: outcome ?? previous?.outcome,
    failed: evt.phase === "failed" || previous?.failed === true,
    updated_at: now,
  };

  let tiles: TileState[];
  if (existingIdx >= 0) {
    tiles = state.tiles.slice();
    // Move the updated tile to the head so the newest activity is on top.
    tiles.splice(existingIdx, 1);
    tiles.unshift(next);
  } else {
    tiles = [next, ...state.tiles];
    if (tiles.length > TILE_CAP) tiles.length = TILE_CAP;
  }

  const ticker = [evt, ...state.ticker].slice(0, TICKER_CAP);

  // KPI accumulators - only count on the terminal audit.done frame so
  // one event contributes exactly once, matching the audit log rate.
  const shouldCount = evt.stage === "audit" && evt.phase === "done";
  const ratePings = shouldCount ? [...state.ratePings, now] : state.ratePings;
  const tierCounts = shouldCount && next.tier
    ? { ...state.tierCounts, [next.tier]: (state.tierCounts[next.tier] ?? 0) + 1 }
    : state.tierCounts;
  const gateCounts = shouldCount && next.gate_decision
    ? {
        ...state.gateCounts,
        [next.gate_decision]: (state.gateCounts[next.gate_decision] ?? 0) + 1,
      }
    : state.gateCounts;

  return { tiles, ticker, ratePings, tierCounts, gateCounts };
}

function pickString(detail: Record<string, unknown>, key: string): string | undefined {
  const v = detail[key];
  return typeof v === "string" ? v : undefined;
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

const STATUS_LABEL: Record<LiveConnectionStatus, string> = {
  idle: "idle",
  connecting: "connecting",
  open: "live",
  closed: "closed",
  unsupported: "SSE unsupported",
};

export function LiveRoute({ client }: Props) {
  const [state, dispatch] = useReducer(reducer, initialState);

  // Compose the URL once - env-var based in dev, same-origin in prod
  // (Static Web Apps deployment shares origin with the read API).
  const url = useMemo(() => {
    const cfg = loadConfig();
    const base =
      cfg.readApiBaseUrl ||
      (typeof window !== "undefined" ? window.location.origin : "");
    return `${base.replace(/\/$/, "")}/live/stream`;
  }, []);

  const { status, lastError } = useLiveStream({
    url,
    onEvent: (event) => dispatch({ kind: "event", event }),
  });

  // Periodic tick to age out stale rate pings.
  useEffect(() => {
    const handle = window.setInterval(() => {
      dispatch({ kind: "tick", now: Date.now() });
    }, 1000);
    return () => window.clearInterval(handle);
  }, []);

  // Ensure the client reference doesn't warn - Live doesn't hit REST but the
  // panel contract passes a client in case a future variant needs it.
  const clientRef = useRef(client);
  clientRef.current = client;

  const eps = (state.ratePings.length / (RATE_WINDOW_MS / 1000)).toFixed(1);
  const gateTotal = Object.values(state.gateCounts).reduce((a, b) => a + b, 0);
  const tierTotal = Object.values(state.tierCounts).reduce((a, b) => a + b, 0);

  return (
    <div class="live">
      <section class="live-header">
        <div>
          <h2>Live</h2>
          <p class="muted">
            Every tile is one control-plane action flowing through the pipeline. The
            wire is <code>GET /live/stream</code>.
          </p>
        </div>
        <div class={`live-status live-status-${status}`}>
          <span class="live-status-dot" />
          {STATUS_LABEL[status]}
          {lastError ? <span class="muted"> — {lastError}</span> : null}
        </div>
      </section>

      <section class="grid live-kpis">
        <div class="card kpi">
          <span class="label">Events / sec (60s)</span>
          <span class="value">{eps}</span>
        </div>
        <div class="card kpi">
          <span class="label">Tier mix (60s)</span>
          <span class="value live-mix">
            {(["t0", "t1", "t2"] as const).map((t) => (
              <span key={t} class={`live-tier live-tier-${t}`}>
                {t.toUpperCase()} {pct(state.tierCounts[t] ?? 0, tierTotal)}%
              </span>
            ))}
          </span>
        </div>
        <div class="card kpi">
          <span class="label">Gate mix (60s)</span>
          <span class="value live-mix">
            {(["auto", "hil", "abstain", "deny"] as const).map((g) => (
              <span key={g} class={`live-gate live-gate-${g}`}>
                {g} {pct(state.gateCounts[g] ?? 0, gateTotal)}%
              </span>
            ))}
          </span>
        </div>
      </section>

      <section class="live-swarm" aria-label="live control-plane activity">
        {state.tiles.map((tile) => (
          <LiveTile key={tile.event_id} tile={tile} />
        ))}
        {state.tiles.length === 0 ? (
          <div class="live-empty">
            Waiting for the first event...
          </div>
        ) : null}
      </section>

      <section class="card live-ticker" aria-label="audit stream">
        <h2>Audit stream <span class="muted">· append-only</span></h2>
        <ol>
          {state.ticker.map((evt) => (
            <li key={`${evt.event_id}-${evt.stage}-${evt.phase}-${evt.ts}`}>
              <span class="muted">{shortTime(evt.ts)}</span>{" "}
              <span class={`live-tier live-tier-${(evt.detail?.tier as string) ?? "t0"}`}>
                {String(evt.detail?.tier ?? "t?").toUpperCase()}
              </span>{" "}
              <code>{evt.event_id.slice(0, 12)}</code>{" "}
              <span>
                {evt.stage}.{evt.phase}
              </span>
              {evt.detail?.rule ? (
                <>
                  {" -> "}
                  <span>{String(evt.detail.rule)}</span>
                </>
              ) : null}
              {evt.detail?.gate_decision ? (
                <>
                  {" · "}
                  <span class={`live-gate live-gate-${String(evt.detail.gate_decision)}`}>
                    {String(evt.detail.gate_decision)}
                  </span>
                </>
              ) : null}
            </li>
          ))}
          {state.ticker.length === 0 ? (
            <li class="muted">No stage frames yet.</li>
          ) : null}
        </ol>
      </section>
    </div>
  );
}

function LiveTile({ tile }: { readonly tile: TileState }) {
  const tier = tile.tier ?? "t?";
  const gate = tile.gate_decision ?? "";
  return (
    <div
      class={`live-tile live-tile-${tier} live-tile-gate-${gate}`}
      data-failed={tile.failed ? "1" : "0"}
    >
      <div class="live-tile-top">
        <span class={`live-tier live-tier-${tier}`}>{tier.toUpperCase()}</span>
        <span class="live-tile-stage">{tile.current_stage}</span>
      </div>
      <div class="live-tile-title" title={tile.rule ?? tile.action_type}>
        {tile.rule ?? tile.action_type ?? "(routing)"}
      </div>
      <div class="live-tile-meta">
        <span class="muted">{tile.scope ?? "-"}</span>
        <code>{tile.event_id.slice(0, 12)}</code>
      </div>
    </div>
  );
}

function pct(n: number, d: number): number {
  return d > 0 ? Math.round((n / d) * 100) : 0;
}

function shortTime(iso: string): string {
  // ISO-8601 with millisecond precision -> "HH:MM:SS.mmm".
  const match = iso.match(/T(\d\d:\d\d:\d\d\.\d{3})/);
  return match?.[1] ?? iso;
}
