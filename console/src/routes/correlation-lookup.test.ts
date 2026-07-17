import { describe, expect, it } from "vitest";
import { rcaCorrelationHref } from "./rca";
import { traceCorrelationHref } from "./rule-trace";

describe("correlation lookup URLs", () => {
  it("persists the submitted correlation in the canonical route", () => {
    expect(rcaCorrelationHref(" corr/1 ")).toBe("/root-cause-analysis?correlation=corr%2F1");
    expect(traceCorrelationHref(" corr/1 ")).toBe("/trace?correlation=corr%2F1");
  });
});
