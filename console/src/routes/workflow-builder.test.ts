import { describe, expect, test } from "vitest";
import {
  buildGithubNewFileUrl,
  humanizeName,
  suggestDraftFromText,
  suggestStepId,
} from "./workflow-builder";
import type { ActionTypePaletteEntry } from "../workflow/validate";

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

function at(name: string, category: string, description = ""): ActionTypePaletteEntry {
  return {
    name,
    operation: "update",
    category,
    rollback_contract: "pr_revert",
    irreversible: false,
    default_mode: "shadow",
    execution_path: null,
    env_scope: "any",
    hil_tiers: [],
    description,
  };
}

const PALETTE: readonly ActionTypePaletteEntry[] = [
  at("remediate.right-size", "remediation", "Adjust compute count to match utilization"),
  at("ops.scale-out", "ops", "Add capacity"),
  at("ops.restart-service", "ops", "Restart a service"),
  at("remediate.enable-encryption", "remediation", "Turn on encryption at rest"),
  at("remediate.disable-public-access", "remediation", "Remove public network exposure"),
  at("ops.publish-change-summary", "ops", "Publish a change summary"),
  at("ops.failover-primary", "ops", "Fail over the primary"),
];

describe("suggestDraftFromText", () => {
  test("maps a cost intent to the cost signal + right-size and notify actions", () => {
    const s = suggestDraftFromText("When cost spikes, right-size the VM and tell me", PALETTE);
    expect(s).not.toBeNull();
    expect(s!.form.triggerKind).toBe("signal");
    expect(s!.form.signalType).toBe("object.cost-anomaly");
    const actions = s!.form.steps.map((st) => st.action_type_ref);
    expect(actions).toContain("remediate.right-size");
    expect(actions).toContain("ops.publish-change-summary");
    expect(s!.form.steps.every((st) => st.id.length > 0)).toBe(true);
  });

  test("maps a weekly DR drill to a schedule trigger + failover", () => {
    const s = suggestDraftFromText("Every week, rehearse a DR failover", PALETTE);
    expect(s).not.toBeNull();
    expect(s!.form.triggerKind).toBe("schedule");
    expect(s!.form.schedule).toBe("0 3 * * 0");
    expect(s!.form.steps.map((st) => st.action_type_ref)).toContain("ops.failover-primary");
  });

  test("maps a security intent to the security signal + disable-public-access", () => {
    const s = suggestDraftFromText("When a resource is exposed, disable public access", PALETTE);
    expect(s).not.toBeNull();
    expect(s!.form.signalType).toBe("object.security-event");
    expect(s!.form.steps.map((st) => st.action_type_ref)).toContain(
      "remediate.disable-public-access",
    );
  });

  test("abstains on an unmatchable string", () => {
    expect(suggestDraftFromText("qwer zxcv hjkl", PALETTE)).toBeNull();
    expect(suggestDraftFromText("", PALETTE)).toBeNull();
  });

  test("caps the suggested steps at three", () => {
    const s = suggestDraftFromText(
      "encrypt, restart, scale out, right-size, disable public access, failover",
      PALETTE,
    );
    expect(s).not.toBeNull();
    expect(s!.form.steps.length).toBeLessThanOrEqual(3);
  });

  test("suggested step ids are unique within the draft", () => {
    const s = suggestDraftFromText("right-size and scale out and restart", PALETTE);
    const ids = s!.form.steps.map((st) => st.id);
    expect(new Set(ids).size).toBe(ids.length);
  });
});

describe("buildGithubNewFileUrl", () => {
  test("returns null when the repo is not owner/repo", () => {
    expect(buildGithubNewFileUrl("", "main", "p.yaml", "x")).toBeNull();
    expect(buildGithubNewFileUrl("not-a-repo", "main", "p.yaml", "x")).toBeNull();
    expect(buildGithubNewFileUrl("a/b/c", "main", "p.yaml", "x")).toBeNull();
  });

  test("builds a new-file URL with url-encoded filename + content", () => {
    const url = buildGithubNewFileUrl(
      "acme/fdai",
      "main",
      "rule-catalog/workflows/x.yaml",
      "name: x\n",
    );
    expect(url).not.toBeNull();
    expect(url!.startsWith("https://github.com/acme/fdai/new/main?")).toBe(true);
    expect(url).toContain("filename=rule-catalog%2Fworkflows%2Fx.yaml");
    expect(url).toContain("value=name%3A+x%0A");
  });

  test("defaults an empty branch to main", () => {
    const url = buildGithubNewFileUrl("acme/fdai", "", "x.yaml", "x");
    expect(url!).toContain("/new/main?");
  });
});
