import { describe, expect, test } from "vitest";
import { pantheonViewFromSearch } from "./pantheon";

describe("Pantheon view routing", () => {
  test("opens the organization chart from its direct link", () => {
    expect(pantheonViewFromSearch(new URLSearchParams("view=org"))).toBe("org");
  });

  test("defaults missing or unknown views to the directory", () => {
    expect(pantheonViewFromSearch(new URLSearchParams())).toBe("directory");
    expect(pantheonViewFromSearch(new URLSearchParams("view=unknown"))).toBe("directory");
  });
});
