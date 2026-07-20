import assert from "node:assert/strict";
import test from "node:test";

import { canonicalTextArtifact, resolveCssFallbacks } from "../src/compiler.js";

test("canonical text artifacts end with exactly one newline", () => {
  assert.equal(canonicalTextArtifact("<svg></svg>").toString(), "<svg></svg>\n");
  assert.equal(canonicalTextArtifact("<svg></svg>\n\n").toString(), "<svg></svg>\n");
});

test("resolves diagram CSS variable fallbacks for static PNG rendering", () => {
  assert.equal(
    resolveCssFallbacks(
      "fill: var(--fdai-diagram-canvas, #faf9f8); color: var(--fdai-diagram-text, #323130);",
    ),
    "fill: #faf9f8; color: #323130;",
  );
});
