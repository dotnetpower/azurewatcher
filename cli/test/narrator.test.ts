/**
 * Unit tests for the narrator seam.
 *
 * Covers config parsing + factory selection, the deterministic tool router over
 * the sample context, and the LLM narrator's tool-calling loop (with fetch
 * stubbed, so no network / no key is needed).
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import {
  createNarrator,
  readLlmConfig,
  resolveDiskLlmConfig,
} from "../src/narrator/index.js";
import { DeterministicNarrator } from "../src/narrator/deterministic.js";
import { LlmNarrator } from "../src/narrator/llm.js";
import { runTool } from "../src/narrator/tools.js";
import type { NarratorContext } from "../src/narrator/types.js";
import { sampleBriefing } from "../src/data/sample-briefing.js";

const sampleCtx: NarratorContext = {
  apiUrl: null,
  payload: sampleBriefing("needs-me"),
};

// Point disk resolution at a path that does not exist so the tests stay
// hermetic regardless of a local (gitignored) resolved-models.json.
const NO_DISK = { LLM_RESOLVED_MODELS_PATH: "/nonexistent-fdai/resolved-models.json" };

describe("readLlmConfig + createNarrator", () => {
  it("returns null and a deterministic narrator with no env", () => {
    expect(readLlmConfig({})).toBeNull();
    expect(createNarrator(NO_DISK).kind).toBe("deterministic");
  });

  it("parses a full config and selects the LLM narrator", () => {
    const env = {
      FDAI_NARRATOR_BASE_URL: "https://api.openai.com/v1",
      FDAI_NARRATOR_API_KEY: "sk-test",
      FDAI_NARRATOR_MODEL: "gpt-4o-mini",
    };
    const cfg = readLlmConfig(env);
    expect(cfg).not.toBeNull();
    expect(cfg?.provider).toBe("openai");
    expect(cfg?.auth).toBe("api-key");
    expect(createNarrator(env).kind).toBe("llm");
  });

  it("detects the azure provider", () => {
    const cfg = readLlmConfig({
      FDAI_NARRATOR_PROVIDER: "azure",
      FDAI_NARRATOR_BASE_URL: "https://x.openai.azure.com",
      FDAI_NARRATOR_API_KEY: "k",
      FDAI_NARRATOR_MODEL: "dep",
    });
    expect(cfg?.provider).toBe("azure");
  });

  it("stays deterministic when the config is partial", () => {
    expect(
      createNarrator({ FDAI_NARRATOR_API_KEY: "only-key", ...NO_DISK }).kind,
    ).toBe("deterministic");
  });

  it("resolves a keyless azure-ad narrator from resolved-models.json", () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "fdai-narr-"));
    const file = path.join(dir, "resolved-models.json");
    fs.writeFileSync(
      file,
      JSON.stringify({
        narrator: { endpoint: "https://example.openai.azure.com/", deployment: "gpt-4o-mini" },
      }),
    );
    const cfg = resolveDiskLlmConfig({ LLM_RESOLVED_MODELS_PATH: file });
    expect(cfg?.provider).toBe("azure");
    expect(cfg?.auth).toBe("azure-ad");
    expect(cfg?.model).toBe("gpt-4o-mini");
    expect(createNarrator({ LLM_RESOLVED_MODELS_PATH: file }).kind).toBe("llm");
    fs.rmSync(dir, { recursive: true, force: true });
  });

  it("ignores resolved-models.json without a narrator block", () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "fdai-narr-"));
    const file = path.join(dir, "resolved-models.json");
    fs.writeFileSync(file, JSON.stringify({ region: "koreacentral" }));
    expect(resolveDiskLlmConfig({ LLM_RESOLVED_MODELS_PATH: file })).toBeNull();
    fs.rmSync(dir, { recursive: true, force: true });
  });
});

describe("DeterministicNarrator (sample context)", () => {
  const n = new DeterministicNarrator();

  it("answers kpi from the sample tools", async () => {
    const a = await n.answer("show kpi", sampleCtx);
    expect(a).toMatch(/events=\d+/);
    expect(a).toContain("tiers[");
  });

  it("lists the HIL queue", async () => {
    const a = await n.answer("hil queue", sampleCtx);
    expect(a).toContain("payments-api");
  });

  it("returns card detail for a number", async () => {
    const a = await n.answer("1", sampleCtx);
    expect(a).toContain("payments-api");
    expect(a).toContain("pull request");
  });

  it("renders answers in the ctx locale (ko), English by default", async () => {
    const en = await n.answer("a", sampleCtx);
    const ko = await n.answer("a", { ...sampleCtx, locale: "ko" });
    // Default English hint is unchanged.
    expect(en).toContain("(read-only)");
    // ko is localized: differs from English and drops the English marker.
    expect(ko).not.toBe(en);
    expect(ko).not.toContain("(read-only)");
    expect(ko.length).toBeGreaterThan(0);
  });

  it("falls back to English for a lagging locale key (sample colour)", async () => {
    // ko does not translate `narrator.samplePayments`; the English source
    // renders (mandatory fallback), never a blank.
    const ko = await n.answer("payments", { ...sampleCtx, locale: "ko" });
    expect(ko).toContain("payments-api");
  });

  it("falls back with live state + LLM hint for free-form input", async () => {
    const a = await n.answer("\uc548\ub155", sampleCtx); // Korean
    expect(a).toContain("events=");
    expect(a).toContain("FDAI_NARRATOR");
  });
});

describe("console tools", () => {
  it("get_kpi summarizes the sample payload", async () => {
    const out = await runTool("get_kpi", {}, sampleCtx);
    expect(out).toMatch(/events=1204/);
  });

  it("get_recent_audit is unavailable in sample mode", async () => {
    const out = await runTool("get_recent_audit", {}, sampleCtx);
    expect(out).toContain("not available in sample mode");
  });

  it("throws on an unknown tool", async () => {
    await expect(runTool("nope", {}, sampleCtx)).rejects.toThrow(/unknown/);
  });

  it("set_view drives an attached screen and is read-only", async () => {
    const calls: Array<Record<string, unknown>> = [];
    const ctx: NarratorContext = {
      ...sampleCtx,
      screen: {
        setView: (patch) => {
          calls.push(patch);
          return "Showing OVERVIEW.";
        },
      },
    };
    const out = await runTool("set_view", { mode: "overview" }, ctx);
    expect(out).toBe("Showing OVERVIEW.");
    expect(calls).toEqual([{ mode: "overview" }]);
  });

  it("set_view is a no-op without a screen", async () => {
    const out = await runTool("set_view", { mode: "overview" }, sampleCtx);
    expect(out).toContain("no screen attached");
  });

  it("query_inventory asks for a kql query when none is given", async () => {
    const out = await runTool("query_inventory", {}, sampleCtx);
    expect(out).toContain("kql");
  });
});

describe("LlmNarrator tool-calling loop (fetch stubbed)", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("calls a tool then answers from its result", async () => {
    const calls: Array<Record<string, unknown>> = [];
    const fetchMock = vi.fn(async (_url: string, init: { body: string }) => {
      const body = JSON.parse(init.body);
      calls.push(body);
      if (calls.length === 1) {
        // First round: ask to call get_kpi.
        return new Response(
          JSON.stringify({
            choices: [
              {
                message: {
                  role: "assistant",
                  content: null,
                  tool_calls: [
                    {
                      id: "call_1",
                      type: "function",
                      function: { name: "get_kpi", arguments: "{}" },
                    },
                  ],
                },
              },
            ],
          }),
          { status: 200 },
        );
      }
      // Second round: final grounded answer.
      return new Response(
        JSON.stringify({
          choices: [{ message: { role: "assistant", content: "1204 events." } }],
        }),
        { status: 200 },
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    const narrator = new LlmNarrator({
      provider: "openai",
      baseUrl: "https://api.openai.com/v1",
      apiKey: "sk-test",
      model: "gpt-4o-mini",
      apiVersion: "2024-08-01-preview",
    });
    const answer = await narrator.answer("how many events?", sampleCtx);

    expect(answer).toBe("1204 events.");
    expect(fetchMock).toHaveBeenCalledTimes(2);
    // The second request must include the tool result grounding.
    const secondBody = calls[1] as { messages: Array<{ role: string; content: string }> };
    const toolMsg = secondBody.messages.find((m) => m.role === "tool");
    expect(toolMsg?.content).toMatch(/events=1204/);
  });

  it("injects an L3 locale directive for ko, none for en", async () => {
    const bodies: Array<{ messages: Array<{ role: string; content: string }> }> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, init: { body: string }) => {
        bodies.push(JSON.parse(init.body));
        return new Response(
          JSON.stringify({
            choices: [{ message: { role: "assistant", content: "ok" } }],
          }),
          { status: 200 },
        );
      }),
    );
    const narrator = new LlmNarrator({
      provider: "openai",
      baseUrl: "https://api.openai.com/v1",
      apiKey: "sk-test",
      model: "gpt-4o-mini",
      apiVersion: "2024-08-01-preview",
    });

    await narrator.answer("status?", sampleCtx); // en (default)
    await narrator.answer("status?", { ...sampleCtx, locale: "ko" });

    const systemMsgs = (b: (typeof bodies)[number]) =>
      b.messages.filter((m) => m.role === "system");
    // en: only the base prompt, no added locale directive.
    expect(systemMsgs(bodies[0]!)).toHaveLength(1);
    expect(systemMsgs(bodies[0]!).map((m) => m.content).join("\n")).not.toMatch(
      /exactly as provided/,
    );
    // ko: an extra directive that names Korean and preserves the pipeline.
    expect(systemMsgs(bodies[1]!)).toHaveLength(2);
    const koDirective = systemMsgs(bodies[1]!)[1]!.content;
    expect(koDirective).toContain("Korean");
    expect(koDirective).toMatch(/exactly as provided/);
  });

  it("degrades to an error string when the model call fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("nope", { status: 500, statusText: "err" })),
    );
    const narrator = new LlmNarrator({
      provider: "openai",
      baseUrl: "https://api.openai.com/v1",
      apiKey: "k",
      model: "m",
      apiVersion: "v",
    });
    const answer = await narrator.answer("hi", sampleCtx);
    expect(answer).toContain("narrator error");
  });
});
