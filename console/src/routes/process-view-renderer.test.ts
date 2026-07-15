import { describe, expect, test } from "vitest";
import { nextTabIndex, SUPPORTED_REPORT_WIDGET_TYPES } from "./process-view-renderer";

describe("report widget registry", () => {
  test("covers every widget type used by the shipped reports", () => {
    expect(SUPPORTED_REPORT_WIDGET_TYPES).toEqual(new Set([
      "query_value",
      "bar_chart",
      "timeseries",
      "top_list",
      "table",
      "list_stream",
      "check_status",
      "topology_map",
      "group",
      "tabs",
    ]));
  });

  test("implements wrapping tab keyboard navigation", () => {
    expect(nextTabIndex(0, "ArrowRight", 3)).toBe(1);
    expect(nextTabIndex(2, "ArrowRight", 3)).toBe(0);
    expect(nextTabIndex(0, "ArrowLeft", 3)).toBe(2);
    expect(nextTabIndex(1, "Home", 3)).toBe(0);
    expect(nextTabIndex(1, "End", 3)).toBe(2);
    expect(nextTabIndex(1, "Enter", 3)).toBe(1);
  });
});
