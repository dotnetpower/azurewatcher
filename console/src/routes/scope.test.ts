import { describe, expect, it, vi } from "vitest";
import { copyScopeArtifact, includedScopeEntryCount } from "./scope";

describe("scope eligibility", () => {
  it("excludes policy exclusions from operational counts", () => {
    expect(includedScopeEntryCount([
      { state: "included" },
      { state: "excluded" },
    ] as never)).toBe(1);
  });
});

describe("scope artifact clipboard", () => {
  it("reports copied only after the clipboard write succeeds", async () => {
    const writeText = vi.fn(async () => undefined);

    await expect(copyScopeArtifact({ writeText }, "action:\n")).resolves.toBe("copied");
    expect(writeText).toHaveBeenCalledWith("action:\n");
  });

  it("reports failed when clipboard access is missing or rejects", async () => {
    await expect(copyScopeArtifact(undefined, "artifact")).resolves.toBe("failed");
    await expect(copyScopeArtifact({
      writeText: vi.fn(async () => { throw new Error("denied"); }),
    }, "artifact")).resolves.toBe("failed");
  });
});
