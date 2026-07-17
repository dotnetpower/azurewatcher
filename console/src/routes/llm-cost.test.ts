import { describe, expect, test } from "vitest";
import { decodeLlmCost, formatLlmCost, llmCostCorrelationHref } from "./llm-cost";

const summary = {
  key: "total",
  invocations: 1,
  priced_invocations: 1,
  prompt_tokens: 10,
  completion_tokens: 5,
  total_tokens: 15,
  cost: "0.01",
  currency: "USD",
  has_unpriced: false,
  has_mixed_currency: false,
};

describe("LLM cost provenance", () => {
  test("does not present a mixed-currency raw sum as a total", () => {
    expect(formatLlmCost({
      cost: "42.00",
      currency: "MIXED",
      has_mixed_currency: true,
    })).toBe("Mixed currencies");
    expect(formatLlmCost(summary)).toBe("0.01 USD");
  });

  test("links conversation rollups to correlation-scoped audit evidence", () => {
    expect(llmCostCorrelationHref("corr-1")).toBe("/audit?correlation=corr-1");
  });

  test("decodes the latest measured invocation timestamp", () => {
    const decoded = decodeLlmCost({
      source: "metering",
      latest_occurred_at: "2026-07-10T09:00:00+00:00",
      currency: "USD",
      invocations: 1,
      total: summary,
      by_mode: [],
      by_conversation: [],
      by_conversation_truncated: false,
      conversation_count: 0,
      by_day: [],
      by_month: [],
    });

    expect(decoded.latest_occurred_at).toBe("2026-07-10T09:00:00+00:00");
  });
});
