import { describe, expect, it } from "vitest";
import { INITIAL_FORM } from "./workflow-builder.model";
import {
  addDraftStep,
  coerceDraftParam,
  moveDraftStep,
  removeDraftStep,
  setDraftParam,
  setDraftStepAction,
} from "./workflow-builder.editor";

describe("workflow draft editor", () => {
  it("adds, reorders, and removes steps without mutating the source form", () => {
    const original = structuredClone(INITIAL_FORM);
    const first = setDraftStepAction(original, 0, "ops.restart-service");
    const added = setDraftStepAction(addDraftStep(first), 1, "ops.publish-change-summary");
    const moved = moveDraftStep(added, 1, -1);
    const removed = removeDraftStep(moved, 0);

    expect(original).toEqual(INITIAL_FORM);
    expect(moved.steps.map((step) => step.action_type_ref)).toEqual([
      "ops.publish-change-summary",
      "ops.restart-service",
    ]);
    expect(removed.steps.map((step) => step.id)).toEqual(["publish_change_summary"]);
  });

  it("preserves custom ids while suggesting ids for untouched steps", () => {
    const suggested = setDraftStepAction(INITIAL_FORM, 0, "ops.restart-service");
    suggested.steps[0]!.id = "custom_restart";
    const changed = setDraftStepAction(suggested, 0, "ops.scale-out");

    expect(changed.steps[0]!.id).toBe("custom_restart");
    expect(suggested.steps[0]!.action_type_ref).toBe("ops.restart-service");
  });

  it("edits primitive parameters without converting every value to text", () => {
    const withNumber = setDraftParam(
      INITIAL_FORM,
      0,
      "",
      "retries",
      coerceDraftParam("3", "number"),
    );
    const withBoolean = setDraftParam(
      withNumber,
      0,
      "",
      "urgent",
      coerceDraftParam("true", "boolean"),
    );

    expect(withBoolean.steps[0]!.params).toEqual({ retries: 3, urgent: true });
    expect(INITIAL_FORM.steps[0]!.params).toEqual({});
  });
});
