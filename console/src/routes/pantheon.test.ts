import { describe, expect, test } from "vitest";
import { pantheonAgentHref, pantheonViewFromSearch } from "./pantheon";

describe("Pantheon view routing", () => {
  test("opens the organization chart from its direct link", () => {
    expect(pantheonViewFromSearch(new URLSearchParams("view=org"))).toBe("org");
  });

  test("defaults missing or unknown views to the directory", () => {
    expect(pantheonViewFromSearch(new URLSearchParams())).toBe("directory");
    expect(pantheonViewFromSearch(new URLSearchParams("view=unknown"))).toBe("directory");
  });

  test("opens agent focus and preserves live correlation context", () => {
    expect(pantheonAgentHref("Forseti", "correlation-1"))
      .toBe("/agents?view=org&agent=Forseti&correlation=correlation-1");
    expect(pantheonAgentHref("Forseti"))
      .toBe("/agents?view=org&agent=Forseti");
  });
});
