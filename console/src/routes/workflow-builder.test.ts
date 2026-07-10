import { describe, expect, test } from "vitest";
import { humanizeName, suggestStepId } from "./workflow-builder";

/**
 * These tests pin the two pure helpers the Phase-A builder UX relies on:
 *
 * - `humanizeName` renders a dotted workflow id as a readable template-card
 *   title, and
 * - `suggestStepId` derives a valid, unique snake_case step id from an
 *   ActionType ref so the operator never has to invent one by hand.
 */

describe("humanizeName", () => {
  test("dotted / dashed id becomes a capitalized phrase", () => {
    expect(humanizeName("cost-aware-remediation")).toBe("Cost aware remediation");
    expect(humanizeName("dr.failover.drill")).toBe("Dr failover drill");
    expect(humanizeName("predictive_scale")).toBe("Predictive scale");
  });

  test("single token is capitalized", () => {
    expect(humanizeName("scale")).toBe("Scale");
  });
});

describe("suggestStepId", () => {
  test("uses the leaf after the last separator, snake_cased", () => {
    expect(suggestStepId("remediate.right-size", [])).toBe("right_size");
    expect(suggestStepId("ops.scale-out", [])).toBe("scale_out");
    expect(suggestStepId("tool.generate-pdf", [])).toBe("generate_pdf");
  });

  test("de-duplicates against ids already used in the draft", () => {
    expect(suggestStepId("remediate.right-size", ["right_size"])).toBe("right_size_2");
    expect(suggestStepId("remediate.right-size", ["right_size", "right_size_2"])).toBe(
      "right_size_3",
    );
  });

  test("falls back to a safe id when the ref has no alphanumerics", () => {
    expect(suggestStepId("...", [])).toBe("step");
  });
});
