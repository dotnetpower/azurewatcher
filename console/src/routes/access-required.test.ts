import { describe, expect, it } from "vitest";
import { beginAccessCheck, isCurrentAccessCheck } from "./access-required";

describe("Access Required status polling", () => {
  it("allows only the latest overlapping check to commit", () => {
    const generation = { current: 0 };
    const first = beginAccessCheck(generation);
    const second = beginAccessCheck(generation);

    expect(isCurrentAccessCheck(generation, first)).toBe(false);
    expect(isCurrentAccessCheck(generation, second)).toBe(true);
  });
});
