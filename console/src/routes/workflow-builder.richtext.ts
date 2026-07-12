/**
 * Workflow-builder chat rich-text tokenizer - the pure parsing half of the
 * chat's minimal inline markdown. Splitting the parser out of the React
 * component (workflow-builder.chatpanel.tsx) keeps rendering a thin map over
 * these tokens and makes the tricky span/block logic unit-testable without a
 * DOM.
 *
 * SRP: string -> token tree only. No preact, no DOM, no I/O. The engine text
 * this parses is trusted and plain (the deterministic interview writes it);
 * this is presentation structure, never HTML injection.
 */

/** One inline span. `text` spans are literal; the rest are emphasized runs
 * whose `value` is the inner text with the markers already stripped. */
export type InlineToken =
  | { readonly type: "text"; readonly value: string }
  | { readonly type: "strong"; readonly value: string }
  | { readonly type: "em"; readonly value: string }
  | { readonly type: "code"; readonly value: string };

/** One block: a paragraph or a bullet list item, each a run of inline spans. */
export interface Block {
  readonly type: "paragraph" | "bullet";
  readonly spans: readonly InlineToken[];
}

// `**bold**` and `` `code` `` before `*em*` so the longer markers win; each
// body excludes its own marker char so an unterminated run stays literal.
const INLINE_RE = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)/g;

/** Split one line into literal + emphasized spans. Unbalanced or empty
 * markers fall through as literal text rather than throwing. */
export function tokenizeInline(text: string): InlineToken[] {
  const tokens: InlineToken[] = [];
  if (text.length === 0) return tokens;
  let last = 0;
  let m: RegExpExecArray | null;
  const re = new RegExp(INLINE_RE); // fresh lastIndex per call (reentrant)
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) tokens.push({ type: "text", value: text.slice(last, m.index) });
    const tok = m[0];
    if (tok.startsWith("**")) tokens.push({ type: "strong", value: tok.slice(2, -2) });
    else if (tok.startsWith("`")) tokens.push({ type: "code", value: tok.slice(1, -1) });
    else tokens.push({ type: "em", value: tok.slice(1, -1) });
    last = m.index + tok.length;
  }
  if (last < text.length) tokens.push({ type: "text", value: text.slice(last) });
  return tokens;
}

/** Parse the engine's multi-line text into paragraph + bullet blocks. A line
 * starting with `- ` is a bullet; blank lines are dropped. */
export function parseBlocks(text: string): Block[] {
  const blocks: Block[] = [];
  for (const line of text.split("\n")) {
    const trimmed = line.trim();
    if (trimmed.length === 0) continue;
    if (trimmed.startsWith("- ")) {
      blocks.push({ type: "bullet", spans: tokenizeInline(trimmed.slice(2)) });
    } else {
      blocks.push({ type: "paragraph", spans: tokenizeInline(trimmed) });
    }
  }
  return blocks;
}
