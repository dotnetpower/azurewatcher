/**
 * GroundedReply - renders a deck (assistant) turn the way the source-streaming
 * mock does: the answer text types in token by token, then a "Grounded on N
 * sources" pill summarises the reply, and expanding it rolls the cited sources
 * through a slot-machine window (reusing the retrieval-trace slot styles).
 *
 * Honest-data only: every source card is a real ``Citation`` the backend
 * returned (a fact the answer is grounded in). The pill's summary line is the
 * real reply ``source`` descriptor (``llm:<model> - <ms>`` or
 * ``deterministic``). Nothing here is fabricated - it re-presents what the
 * reply already carries.
 *
 * Single responsibility: present one grounded deck reply. No I/O, no
 * privileged calls, only self-cancelling timers.
 */

import { useEffect, useState } from "preact/hooks";

/** One cited source (label + optional value), matching the deck Turn shape. */
interface Citation {
  readonly label: string;
  readonly value?: string;
}

/** Answer text reveal cadence. */
const STREAM_STEP_CHARS = 3;
const STREAM_INTERVAL_MS = 16;
/** Citation slot-machine cadence + window (shared pitch with styles.css). */
const CITE_INTERVAL_MS = 90;
const VISIBLE = 3;
const CARD_PITCH_PX = 40;

export function GroundedReply({
  turnId,
  text,
  citations,
  source,
}: {
  readonly turnId: string;
  readonly text: string;
  readonly citations: readonly Citation[] | undefined;
  readonly source: string | undefined;
}) {
  const cites = citations ?? [];

  // Type the answer in, token by token, once per turn.
  const [shownChars, setShownChars] = useState(0);
  useEffect(() => {
    setShownChars(0);
    if (text.length === 0) return;
    let i = 0;
    const id = window.setInterval(() => {
      i += STREAM_STEP_CHARS;
      setShownChars(i);
      if (i >= text.length) window.clearInterval(id);
    }, STREAM_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [turnId, text.length]);

  const streaming = shownChars < text.length;
  const body = text.slice(0, shownChars);

  // Expandable citation slot-machine: roll the cards in when opened.
  const [open, setOpen] = useState(false);
  const [shownCites, setShownCites] = useState(0);
  useEffect(() => {
    if (!open || cites.length === 0) {
      setShownCites(0);
      return;
    }
    setShownCites(1);
    if (cites.length <= 1) return;
    let i = 1;
    const id = window.setInterval(() => {
      i += 1;
      setShownCites(i);
      if (i >= cites.length) window.clearInterval(id);
    }, CITE_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [open, cites.length]);

  const rolled = Math.max(0, shownCites - VISIBLE);
  const visibleCites = cites.slice(0, shownCites);

  return (
    <div class="deck-gr">
      <div class="deck-turn-body">
        {body.split("\n").map((line, i) => (
          <p key={i} class="deck-turn-line">
            {line}
            {streaming && i === body.split("\n").length - 1 ? (
              <span class="deck-gr-caret" aria-hidden="true" />
            ) : null}
          </p>
        ))}
      </div>

      {!streaming && cites.length > 0 ? (
        <>
          <button
            type="button"
            class="deck-gr-pill"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
          >
            <span class="deck-gr-check" aria-hidden="true">
              {"\u2713"}
            </span>
            <span>
              Grounded on <strong>{cites.length}</strong>{" "}
              {cites.length === 1 ? "source" : "sources"}
            </span>
            {source ? <span class="deck-gr-src muted">{source}</span> : null}
            <span class="deck-gr-more">{open ? "hide sources" : "show sources"}</span>
          </button>

          {open ? (
            <div class="deck-rt-slot deck-gr-slot">
              <ul
                class="deck-rt-strip"
                style={{ transform: `translateY(${-rolled * CARD_PITCH_PX}px)` }}
              >
                {visibleCites.map((c, i) => (
                  <li key={`${c.label}-${i}`} class="deck-rt-card">
                    <span class="deck-rt-badge">{i + 1}</span>
                    <span class="deck-rt-txt">
                      <span class="deck-rt-k">{c.label}</span>
                      {c.value !== undefined ? (
                        <span class="deck-rt-v">{c.value}</span>
                      ) : null}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
