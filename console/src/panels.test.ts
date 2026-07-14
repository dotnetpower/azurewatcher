import { describe, expect, test } from "vitest";
import {
  bottomRailPanels,
  DEFAULT_PANEL_ID,
  panelForId,
  panelsInGroup,
  resolvePanels,
} from "./panels";

describe("panel navigation placement", () => {
  test("places the incident roster in Now after Live", () => {
    const now = panelsInGroup("now").map((panel) => panel.id);
    expect(now.slice(0, 3)).toEqual(["live", "incidents", "agents"]);
    expect(panelForId("incidents").id).toBe("incidents");
  });

  test("keeps Settings out of the Overview flyout", () => {
    expect(panelsInGroup("overview").map((panel) => panel.id)).toEqual(["dashboard"]);
    expect(panelForId("operating-outcomes").placement).toBe("drilldown");
    expect(panelForId("control-assurance").placement).toBe("drilldown");
    expect(panelForId("verticals").placement).toBe("drilldown");
    expect(panelForId("trust-routing").placement).toBe("drilldown");
    expect(panelForId("llm-cost").placement).toBe("drilldown");
  });

  test("pins Settings to the bottom rail without changing its route", () => {
    expect(bottomRailPanels().map((panel) => panel.id)).toEqual(["settings"]);
    expect(resolvePanels().some((panel) => panel.id === "settings")).toBe(true);
    expect(panelForId("settings").id).toBe("settings");
    expect(DEFAULT_PANEL_ID).toBe("dashboard");
  });
});