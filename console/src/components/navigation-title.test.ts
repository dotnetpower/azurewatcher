import { readFileSync } from "node:fs";
import { describe, expect, test } from "vitest";
import { navigationDomainForPanel } from "./navigation-title";

const livePanels = readFileSync(
  new URL("../routes/live.panels.tsx", import.meta.url),
  "utf8",
);

describe("navigation title", () => {
  test("omits roots that duplicate their domain and standalone utilities", () => {
    expect(navigationDomainForPanel("agents")).toBeNull();
    expect(navigationDomainForPanel("labs")).toBeNull();
    expect(navigationDomainForPanel("settings-general")).toBe("Settings");
  });

  test("returns the domain for the Dashboard and detail panels", () => {
    expect(navigationDomainForPanel("dashboard")).toBe("Overview");
    expect(navigationDomainForPanel("llm-cost")).toBe("Overview");
    expect(navigationDomainForPanel("live")).toBe("Operations");
    expect(navigationDomainForPanel("incidents")).toBe("Operations");
    expect(navigationDomainForPanel("scheduler-runs")).toBe("Operations");
  });

  test("keeps Live on the shared page-title breadcrumb", () => {
    expect(livePanels).toContain("<PageHeader");
    expect(livePanels).toContain('title={appT("nav.panel.live")}');
  });
});
