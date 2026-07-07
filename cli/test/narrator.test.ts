/**
 * Unit tests for the narrator seam.
 *
 * Covers config parsing + factory selection, the deterministic tool router over
 * the sample context, and the LLM narrator's tool-calling loop (with fetch
 * stubbed, so no network / no key is needed).
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import { createNarrator, readLlmConfig } from "../src/narrator/index.js";
import { DeterministicNarrator } from "../src/narrator/deterministic.js";
import { LlmNarrator } from "../src/narrator/llm.js";
import { runTool } from "../src/narrator/tools.js";
import type { NarratorContext } from "../src/narrator/types.js";
import { sampleBriefing } from "../src/data/sample-briefing.js";

const sampleCtx: NarratorContext = {
  apiUrl: null,
  payload: sampleBriefing("needs-me"),
};

describe("readLlmConfig + createNarrator", () => {
  it("returns null and a deterministic narrator with no env", () => {
    expect(readLlmConfig({})).toBeNull();
    expect(createNarrator({}).kind).toBe("deterministic");
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
    expect(createNarrator({ FDAI_NARRATOR_API_KEY: "only-key" }).kind).toBe(
      "deterministic",
    );
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
