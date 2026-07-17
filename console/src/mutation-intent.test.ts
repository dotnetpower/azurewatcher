import { describe, expect, it, vi } from "vitest";
import { identityForMutationIntent } from "./mutation-intent";

describe("mutation intent identity", () => {
  it("reuses a key for retries and rotates it when the intent changes", () => {
    const createKey = vi.fn()
      .mockReturnValueOnce("intent-1")
      .mockReturnValueOnce("intent-2");
    const first = identityForMutationIntent(null, "same-input", createKey);
    const retry = identityForMutationIntent(first, "same-input", createKey);
    const changed = identityForMutationIntent(retry, "changed-input", createKey);

    expect(retry).toBe(first);
    expect(changed.idempotencyKey).toBe("intent-2");
    expect(createKey).toHaveBeenCalledTimes(2);
  });
});
