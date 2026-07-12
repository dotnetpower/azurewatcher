import { describe, expect, it } from "vitest";
import { parseBlocks, tokenizeInline } from "./workflow-builder.richtext";

describe("workflow-builder richtext tokenizer", () => {
  it("returns no tokens for an empty string", () => {
    expect(tokenizeInline("")).toEqual([]);
  });

  it("keeps plain text as a single literal span", () => {
    expect(tokenizeInline("just words")).toEqual([{ type: "text", value: "just words" }]);
  });

  it("parses bold, em, and code with markers stripped", () => {
    expect(tokenizeInline("a **b** c")).toEqual([
      { type: "text", value: "a " },
      { type: "strong", value: "b" },
      { type: "text", value: " c" },
    ]);
    expect(tokenizeInline("run `vm-1` now")).toEqual([
      { type: "text", value: "run " },
      { type: "code", value: "vm-1" },
      { type: "text", value: " now" },
    ]);
    expect(tokenizeInline("*soft*")).toEqual([{ type: "em", value: "soft" }]);
  });

  it("prefers the longer bold marker over em", () => {
    const toks = tokenizeInline("**strong**");
    expect(toks).toEqual([{ type: "strong", value: "strong" }]);
  });

  it("leaves an unterminated marker as literal text (no throw)", () => {
    expect(tokenizeInline("**oops")).toEqual([{ type: "text", value: "**oops" }]);
    expect(tokenizeInline("a `code with no close")).toEqual([
      { type: "text", value: "a `code with no close" },
    ]);
  });

  it("is reentrant: repeated calls do not leak regex lastIndex", () => {
    const a = tokenizeInline("**x**");
    const b = tokenizeInline("**x**");
    expect(a).toEqual(b);
  });

  it("parseBlocks splits paragraphs and bullets, dropping blank lines", () => {
    const blocks = parseBlocks("Intro line\n\n- first **item**\n- second");
    expect(blocks.map((b) => b.type)).toEqual(["paragraph", "bullet", "bullet"]);
    expect(blocks[0]?.spans).toEqual([{ type: "text", value: "Intro line" }]);
    expect(blocks[1]?.spans).toEqual([
      { type: "text", value: "first " },
      { type: "strong", value: "item" },
    ]);
  });

  it("parseBlocks trims surrounding whitespace per line", () => {
    const blocks = parseBlocks("   spaced   ");
    expect(blocks).toEqual([{ type: "paragraph", spans: [{ type: "text", value: "spaced" }] }]);
  });
});
