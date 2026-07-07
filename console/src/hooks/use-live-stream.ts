/**
 * Live stage-event stream hook.
 *
 * Subscribes to the read-API's `GET /live/stream` SSE endpoint via
 * `EventSource`, honours the connection lifecycle (open / closed /
 * reconnecting), and hands raw {@link LiveStageEvent} records to a
 * consumer via a mutable ring buffer.
 *
 * The hook never issues privileged calls - it is a pure read consumer.
 * SSE reconnection is delegated to the browser (EventSource
 * automatically retries with a 3s default delay); `Last-Event-ID`
 * flows back to the server on retry so replay-capable adapters can
 * resume from the gap. Upstream today has no replay (audit page has
 * full history), and the FE keeps rendering when reconnection lands.
 */

import { useEffect, useRef, useState } from "preact/hooks";

/** Stage identifier - mirrors {@link fdai.shared.providers.stage_publisher.StageName}. */
export type LiveStageName =
  | "ingest"
  | "route"
  | "verify"
  | "gate"
  | "execute"
  | "audit";

/** Stage phase - mirrors {@link StagePhase}. */
export type LiveStagePhase = "begin" | "progress" | "done" | "failed";

/** One decoded stage frame from the SSE wire. */
export interface LiveStageEvent {
  readonly event_id: string;
  readonly correlation_id: string;
  readonly stage: LiveStageName;
  readonly phase: LiveStagePhase;
  readonly ts: string;
  readonly detail?: Record<string, unknown>;
  readonly error?: string;
}

/** Status of the underlying EventSource. */
export type LiveConnectionStatus =
  | "idle"
  | "connecting"
  | "open"
  | "closed"
  | "unsupported";

export interface UseLiveStreamOptions {
  /** Absolute or relative URL to the SSE endpoint. */
  readonly url: string;
  /** Called for every decoded stage event. */
  readonly onEvent: (event: LiveStageEvent) => void;
  /** Optional connection-status observer. */
  readonly onStatus?: (status: LiveConnectionStatus) => void;
  /** Send credentials (cookies) with the request. Same-origin
   *  production deployments need this; cross-origin dev does not. */
  readonly withCredentials?: boolean;
}

export interface UseLiveStreamResult {
  readonly status: LiveConnectionStatus;
  /** Best-effort last error the browser reported. */
  readonly lastError: string | null;
}

/**
 * Attach an `EventSource` to the SSE endpoint. Every decoded frame is
 * passed to `onEvent` (in a `useRef` so re-renders do not tear the
 * subscription). The hook cleans up on unmount.
 */
export function useLiveStream(options: UseLiveStreamOptions): UseLiveStreamResult {
  const [status, setStatus] = useState<LiveConnectionStatus>(
    typeof EventSource === "undefined" ? "unsupported" : "idle",
  );
  const [lastError, setLastError] = useState<string | null>(null);

  const onEventRef = useRef(options.onEvent);
  const onStatusRef = useRef(options.onStatus);
  onEventRef.current = options.onEvent;
  onStatusRef.current = options.onStatus;

  const url = options.url;
  const withCredentials = options.withCredentials ?? false;

  useEffect(() => {
    if (typeof EventSource === "undefined") return undefined;

    let cancelled = false;
    setStatus("connecting");
    onStatusRef.current?.("connecting");

    const source = new EventSource(url, { withCredentials });

    // Note: the server emits `event: stage` for real transitions and
    // `event: hello` on connect. We only forward `stage` frames; the
    // `hello` frame is observability-only.
    source.addEventListener("stage", (raw) => {
      if (cancelled) return;
      const messageEvent = raw as MessageEvent;
      try {
        const parsed = JSON.parse(messageEvent.data) as LiveStageEvent;
        onEventRef.current(parsed);
      } catch (err) {
        setLastError(err instanceof Error ? err.message : String(err));
      }
    });

    source.onopen = () => {
      if (cancelled) return;
      setStatus("open");
      setLastError(null);
      onStatusRef.current?.("open");
    };

    source.onerror = () => {
      if (cancelled) return;
      // EventSource auto-reconnects for transient errors; when the
      // browser gives up (readyState === CLOSED) we surface "closed".
      const nextStatus: LiveConnectionStatus =
        source.readyState === EventSource.CLOSED ? "closed" : "connecting";
      setStatus(nextStatus);
      onStatusRef.current?.(nextStatus);
    };

    return () => {
      cancelled = true;
      source.close();
      setStatus("closed");
      onStatusRef.current?.("closed");
    };
  }, [url, withCredentials]);

  return { status, lastError };
}
