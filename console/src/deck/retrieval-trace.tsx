/**
 * RetrievalTrace - the deck's "preparing answer" surface.
 *
 * Shown while a turn is pending, in place of a bare typing indicator. It
 * makes the grounding visible: the deck streams the read-only sources it
 * is consulting (the current screen snapshot) in a slot-machine window
 * while it waits for the backend reply. This asserts the console's
 * read-only, narrator-is-a-translator contract as a UI gesture - the
 * deck reads and cites, it never executes.
 *
 * Honest-data only: every row here comes from data the deck actually
 * holds right now - the published ViewSnapshot (facts) and the backend
 * health descriptor (router / model / mode). It fabricates nothing. When
 * the chat backend later streams real per-stage retrieval events (SSE),
 * this component is the seam that renders them; until then it grounds on
 * the screen the operator is looking at.
 *
 * Single responsibility: render the pending retrieval trace. No I/O, no
 * privileged calls, no side effects beyond a self-cancelling timer.
 */

import { useEffect, useState } from "preact/hooks";
import type { BackendHealth } from "./backend";
import type { ViewSnapshot } from "./context";

/** Fixed card pitch: card height + gap. Keep in sync with styles.css
 *  (.deck-rt-card height + .deck-rt-strip gap). */
const CARD_PITCH_PX = 40;
/** How many source cards stay in the slot window at once. */
const VISIBLE = 3;
/** Cadence of the source cascade. */
const FACT_INTERVAL_MS = 110;

interface Stage {
  readonly label: string;
  readonly detail: string;
  readonly side: "read" | "route";
  readonly done: boolean;
}

function buildStages(
  snapshot: ViewSnapshot | null,
  health: BackendHealth | null,
): readonly Stage[] {
  const stages: Stage[] = [];
  if (snapshot) {
    stages.push({
      label: "Read this screen",
      detail: snapshot.routeLabel,
      side: "read",
      done: true,
    });
  }
  if (health?.router) {
    stages.push({
      label: `Route - chose ${health.router.chose}`,
      detail: health.router.reason,
      side: "route",
      done: true,
    });
  } else if (health?.model) {
    stages.push({ label: "Route", detail: health.model, side: "route", done: true });
  }
  stages.push({
    label: "Consult backend",
    detail: health ? health.mode : "connecting",
    side: "read",
    done: false,
  });
  return stages;
}

export function RetrievalTrace({
  snapshot,
  health,
}: {
  readonly snapshot: ViewSnapshot | null;
  readonly health: BackendHealth | null;
}) {
  const facts = snapshot?.facts ?? [];
  const factCount = facts.length;
  const routeId = snapshot?.routeId ?? "";
  const [shown, setShown] = useState(0);

  // Roll the source cards in one at a time (slot-machine cascade). The
  // timer cancels itself once every fact is shown and on unmount.
  useEffect(() => {
    setShown(factCount === 0 ? 0 : 1);
    if (factCount <= 1) return;
    let i = 1;
    const id = window.setInterval(() => {
      i += 1;
      setShown(i);
      if (i >= factCount) window.clearInterval(id);
    }, FACT_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [routeId, factCount]);

  const stages = buildStages(snapshot, health);
  const rolled = Math.max(0, shown - VISIBLE);
  const visibleFacts = facts.slice(0, shown);

  return (
    <article class="deck-rt" aria-live="polite" aria-label="preparing answer">
      <header class="deck-rt-head">
        <span class="deck-rt-spin" aria-hidden="true" />
        <span class="deck-rt-title">Preparing answer</span>
        <span class="deck-rt-sub muted">grounding on read-only sources</span>
      </header>

      <ol class="deck-rt-stages">
        {stages.map((s, i) => (
          <li key={`${s.label}-${i}`} class={`deck-rt-stage ${s.done ? "is-done" : "is-active"}`}>
            <span class="deck-rt-ico" aria-hidden="true" />
            <span class="deck-rt-slabel">{s.label}</span>
            <span class="deck-rt-detail muted">{s.detail}</span>
            <span class={`deck-rt-side deck-rt-side-${s.side}`}>{s.side}</span>
            {s.done ? <span class="deck-rt-check" aria-hidden="true">{"\u2713"}</span> : null}
          </li>
        ))}
      </ol>

      {factCount > 0 ? (
        <div class="deck-rt-sources">
          <div class="deck-rt-sources-label muted">Reading sources - this screen</div>
          <div class="deck-rt-slot">
            <ul
              class="deck-rt-strip"
              style={{ transform: `translateY(${-rolled * CARD_PITCH_PX}px)` }}
            >
              {visibleFacts.map((f, i) => (
                <li key={`${f.key}-${i}`} class="deck-rt-card">
                  <span class="deck-rt-badge">{f.group ?? "fact"}</span>
                  <span class="deck-rt-txt">
                    <span class="deck-rt-k">{f.key}</span>
                    <span class="deck-rt-v">{f.value === null ? "-" : String(f.value)}</span>
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      ) : null}
    </article>
  );
}
