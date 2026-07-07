/**
 * Live cockpit - a one-screen TUI fed by the REAL pipeline over SSE.
 *
 * Consumes the read API's `/live/stream` (Server-Sent Events), where each
 * `stage` frame is a real StageEvent from an actual ControlLoop run (real rule
 * catalog, T0 engine, Rego). It renders a single screen (alternate buffer, no
 * scrollback churn): live counters + a recent-activity feed on top, and a
 * bottom-fixed input box for narrator questions.
 *
 * Input is edited in raw mode with the REAL terminal cursor at the caret, so
 * Korean/IME composition works; only the top area is repainted on new frames
 * (never the input line), so typing is never disturbed. Read-only throughout.
 */

import { createNarrator } from "./narrator/index.js";
import type { NarratorContext } from "./narrator/types.js";

const TEAL = "\x1b[38;2;99;166;156m";
const STEEL = "\x1b[38;2;110;155;203m";
const PLUM = "\x1b[38;2;168;150;206m";
const DIM = "\x1b[38;2;124;132;139m";
const DUSTY = "\x1b[38;2;208;122;122m";
const RESET = "\x1b[0m";
const ESC = "\x1b";

const out = process.stdout;

interface StageFrame {
  event_id: string;
  correlation_id: string;
  stage: string;
  phase: string;
  ts: string;
  detail?: Record<string, unknown>;
  error?: string;
}

function charWidth(cp: number): number {
  if (
    (cp >= 0x1100 && cp <= 0x115f) ||
    (cp >= 0x2e80 && cp <= 0xa4cf) ||
    (cp >= 0xac00 && cp <= 0xd7a3) ||
    (cp >= 0xf900 && cp <= 0xfaff) ||
    (cp >= 0xfe30 && cp <= 0xfe4f) ||
    (cp >= 0xff00 && cp <= 0xff60) ||
    (cp >= 0xffe0 && cp <= 0xffe6)
  ) {
    return 2;
  }
  return 1;
}
function strWidth(s: string): number {
  let w = 0;
  for (const ch of s) w += charWidth(ch.codePointAt(0)!);
  return w;
}
/** Truncate to a display width, honoring wide chars. */
function clip(s: string, width: number): string {
  let w = 0;
  let outStr = "";
  for (const ch of s) {
    const cw = charWidth(ch.codePointAt(0)!);
    if (w + cw > width) break;
    outStr += ch;
    w += cw;
  }
  return outStr;
}

const tierColor = (t: string): string =>
  t === "t0" ? TEAL : t === "t1" ? STEEL : t === "t2" ? PLUM : DIM;

/** Parse an SSE byte stream and call onFrame for each `stage` event. */
async function consumeSse(
  url: string,
  onFrame: (f: StageFrame) => void,
  onStatus: (s: string) => void,
  signal: AbortSignal,
): Promise<void> {
  try {
    const res = await fetch(url, {
      signal,
      headers: { accept: "text/event-stream" },
    });
    if (!res.ok || !res.body) {
      onStatus(`stream ${res.status}`);
      return;
    }
    onStatus("connected");
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let idx: number;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const block = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        let ev = "message";
        let data = "";
        for (const line of block.split("\n")) {
          if (line.startsWith("event:")) ev = line.slice(6).trim();
          else if (line.startsWith("data:")) data += line.slice(5).trim();
        }
        if (ev === "stage" && data) {
          try {
            onFrame(JSON.parse(data) as StageFrame);
          } catch {
            /* ignore malformed frame */
          }
        }
      }
    }
  } catch (err) {
    if (!signal.aborted) onStatus(`stream error: ${(err as Error).message}`);
  }
}

export async function startCockpit(ctx: NarratorContext): Promise<void> {
  const stdin = process.stdin;
  const apiUrl = ctx.apiUrl!;
  if (!stdin.isTTY || typeof stdin.setRawMode !== "function") {
    // Non-interactive: just tell the caller how to view it live.
    process.stdout.write(
      `${DIM}live cockpit needs a TTY; run in a real terminal (streaming ${apiUrl}/live/stream)${RESET}\n`,
    );
    return;
  }

  const narrator = createNarrator();

  // ---- live state ----------------------------------------------------------
  let events = 0;
  const routed: Record<string, number> = {};
  const gate: Record<string, number> = {};
  let exec = 0;
  let audit = 0;
  let errors = 0;
  const recent: string[] = [];
  let status = "connecting...";
  let lastQ = "";
  let answer = "";

  const fmtFrame = (f: StageFrame): string => {
    const t = f.ts.length >= 19 ? f.ts.slice(11, 19) : f.ts;
    const d = f.detail ?? {};
    const keys = [
      "event_type",
      "routed_to",
      "resource_type",
      "rule",
      "tier",
      "decision",
      "outcome",
      "reason",
    ];
    const bits: string[] = [];
    for (const k of keys) {
      const v = d[k];
      if (v !== undefined && v !== null && v !== "") bits.push(`${k}=${String(v)}`);
    }
    const err = f.error ? ` ERR:${f.error}` : "";
    return `${t} ${f.stage}/${f.phase}${err} ${bits.join(" ")}`;
  };

  const onFrame = (f: StageFrame): void => {
    if (f.stage === "ingest" && f.phase === "done") events++;
    if (f.stage === "route" && f.phase === "done") {
      const r = String(f.detail?.routed_to ?? "?");
      routed[r] = (routed[r] ?? 0) + 1;
    }
    if (f.stage === "gate" && f.phase === "done") {
      const g = String(f.detail?.decision ?? f.detail?.outcome ?? "?");
      gate[g] = (gate[g] ?? 0) + 1;
    }
    if (f.stage === "execute" && f.phase === "done") exec++;
    if (f.stage === "audit" && f.phase === "done") audit++;
    if (f.phase === "failed") errors++;
    recent.push(fmtFrame(f));
    if (recent.length > 1000) recent.shift();
    scheduleTop();
  };

  // ---- rendering -----------------------------------------------------------
  const rows = () => (out.rows && out.rows > 0 ? out.rows : 24);
  const cols = () => (out.columns && out.columns > 0 ? out.columns : 80);
  const write = (s: string): void => void out.write(s);
  const cursorTo = (r: number, c: number): void => write(`${ESC}[${r};${c}H`);

  let buf: string[] = [];
  let cur = 0;
  const history: string[] = [];
  let histIdx: number | null = null;
  let busy = false;
  const promptW = 2;

  const placeCaret = (): void => {
    const caretCol = 1 + promptW + strWidth(buf.slice(0, cur).join(""));
    cursorTo(rows(), caretCol);
  };

  const renderTop = (): void => {
    const R = rows();
    const C = cols();
    const feedRows = Math.max(1, R - 7); // rows 4..(R-4) hold the feed
    write(`${ESC}[?25l`);
    // Title.
    cursorTo(1, 1);
    write(
      `${ESC}[2K${TEAL}fdai operator-console${RESET}${DIM}  LIVE - real pipeline  ${status}${RESET}`,
    );
    // Counters.
    const routeBits = ["t0", "t1", "t2", "abstain"]
      .filter((t) => routed[t])
      .map((t) => `${tierColor(t)}${t.toUpperCase()}:${routed[t]}${RESET}`)
      .join(" ");
    const gateBits = Object.entries(gate)
      .map(([k, v]) => `${k}:${v}`)
      .join(" ");
    cursorTo(2, 1);
    write(
      `${ESC}[2K${DIM}events${RESET} ${events}  ${DIM}route${RESET} ${routeBits || "-"}` +
        `  ${DIM}gate${RESET} ${gateBits || "-"}  ${DIM}exec${RESET} ${exec}` +
        `  ${DIM}audit${RESET} ${audit}  ${errors ? DUSTY : DIM}err${RESET} ${errors}`,
    );
    cursorTo(3, 1);
    write(`${ESC}[2K${DIM}${"\u2500".repeat(Math.min(C, 80))}${RESET}`);
    // Recent feed (newest at the bottom of the feed area).
    const slice = recent.slice(-feedRows);
    for (let i = 0; i < feedRows; i++) {
      cursorTo(4 + i, 1);
      const line = slice[i] ?? "";
      write(`${ESC}[2K${DIM}${clip(line, C - 1)}${RESET}`);
    }
    // Question echo (row R-3) and answer (row R-2).
    cursorTo(R - 3, 1);
    write(`${ESC}[2K${lastQ ? `${TEAL}\u203a${RESET} ${clip(lastQ, C - 3)}` : ""}`);
    cursorTo(R - 2, 1);
    write(`${ESC}[2K${answer ? `${TEAL}\u25c7${RESET} ${clip(answer, C - 3)}` : ""}`);
    placeCaret();
    write(`${ESC}[?25h`);
  };

  let topPending = false;
  const scheduleTop = (): void => {
    if (topPending) return;
    topPending = true;
    setTimeout(() => {
      topPending = false;
      renderTop();
    }, 400);
  };

  const hint = `narrator: ${narrator.kind} - ask a question, /exit - Up/Down history, Ctrl+W word`;
  const renderInput = (): void => {
    const R = rows();
    write(`${ESC}[?25l`);
    cursorTo(R - 1, 1);
    write(`${ESC}[2K${DIM}  ${hint}${RESET}`);
    cursorTo(R, 1);
    write(`${ESC}[2K${TEAL}\u203a ${RESET}${buf.join("")}`);
    placeCaret();
    write(`${ESC}[?25h`);
  };

  // ---- narrator ------------------------------------------------------------
  const ask = (q: string): void => {
    busy = true;
    answer = "...";
    renderTop();
    void narrator
      .answer(q, ctx)
      .then((a) => {
        answer = a;
      })
      .catch((err: unknown) => {
        answer = `(error) ${(err as Error).message}`;
      })
      .finally(() => {
        busy = false;
        renderTop();
        renderInput();
      });
  };

  // ---- input ---------------------------------------------------------------
  const submit = (): void => {
    const q = buf.join("").trim();
    buf = [];
    cur = 0;
    histIdx = null;
    if (q === "") {
      renderInput();
      return;
    }
    if (q === "/exit" || q === "/quit" || q === "/q") {
      finish();
      return;
    }
    if (history[history.length - 1] !== q) history.push(q);
    lastQ = q;
    renderTop();
    renderInput();
    ask(q);
  };

  const onData = (d: string): void => {
    if (d === "\x03") {
      finish();
      return;
    }
    if (busy) return;
    if (d === "\r" || d === "\n") return submit();
    if (d === "\x7f" || d === "\b") {
      if (cur > 0) {
        buf.splice(cur - 1, 1);
        cur--;
        renderInput();
      }
      return;
    }
    if (d === `${ESC}[D`) {
      if (cur > 0) cur--;
      renderInput();
      return;
    }
    if (d === `${ESC}[C`) {
      if (cur < buf.length) cur++;
      renderInput();
      return;
    }
    if (d === `${ESC}[A`) {
      if (history.length === 0) return;
      histIdx = histIdx === null ? history.length - 1 : Math.max(0, histIdx - 1);
      buf = [...history[histIdx]!];
      cur = buf.length;
      renderInput();
      return;
    }
    if (d === `${ESC}[B`) {
      if (histIdx === null) return;
      histIdx += 1;
      if (histIdx >= history.length) {
        histIdx = null;
        buf = [];
      } else buf = [...history[histIdx]!];
      cur = buf.length;
      renderInput();
      return;
    }
    if (d === "\x01" || d === `${ESC}[H`) {
      cur = 0;
      renderInput();
      return;
    }
    if (d === "\x05" || d === `${ESC}[F`) {
      cur = buf.length;
      renderInput();
      return;
    }
    if (d === "\x17") {
      let i = cur;
      while (i > 0 && buf[i - 1] === " ") i--;
      while (i > 0 && buf[i - 1] !== " ") i--;
      buf.splice(i, cur - i);
      cur = i;
      renderInput();
      return;
    }
    if (d === "\x15") {
      buf = [];
      cur = 0;
      renderInput();
      return;
    }
    if (d === "\x04") {
      if (buf.length === 0) finish();
      return;
    }
    if (d.startsWith(ESC)) return;
    const nl = d.search(/[\r\n]/);
    const printable = (nl >= 0 ? d.slice(0, nl) : d).replace(/[\u0000-\u001f]/g, "");
    if (printable) {
      const ins = [...printable];
      buf.splice(cur, 0, ...ins);
      cur += ins.length;
    }
    if (nl >= 0) return submit();
    renderInput();
  };

  // ---- lifecycle -----------------------------------------------------------
  const abort = new AbortController();
  let done!: () => void;
  const finished = new Promise<void>((resolve) => {
    done = resolve;
  });
  const finish = (): void => {
    abort.abort();
    stdin.removeListener("data", onData);
    out.removeListener("resize", onResize);
    write(`${ESC}[?25h`);
    write(`${ESC}[?1049l`); // leave alternate screen
    if (typeof stdin.setRawMode === "function") stdin.setRawMode(false);
    stdin.pause();
    stdin.unref?.();
    done();
  };
  const onResize = (): void => {
    renderTop();
    renderInput();
  };

  // Enter alternate screen, hide cursor, draw.
  write(`${ESC}[?1049h${ESC}[2J`);
  stdin.setRawMode(true);
  stdin.setEncoding("utf8");
  stdin.resume();
  renderTop();
  renderInput();
  stdin.on("data", onData);
  out.on("resize", onResize);

  void consumeSse(
    `${apiUrl.replace(/\/$/, "")}/live/stream`,
    onFrame,
    (s) => {
      status = s;
      scheduleTop();
    },
    abort.signal,
  );

  return finished;
}
