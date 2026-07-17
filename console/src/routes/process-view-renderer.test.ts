import { describe, expect, test, vi } from "vitest";
import {
  activateTabByKey,
  barWidthPercent,
  nextTabIndex,
  numericBarValue,
  SUPPORTED_REPORT_WIDGET_TYPES,
} from "./process-view-renderer";

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

  test("moves DOM focus with roving tab selection", () => {
    const focus = vi.fn();
    expect(activateTabByKey(0, "ArrowRight", 3, focus)).toBe(1);
    expect(focus).toHaveBeenCalledWith(1);
  });

  test("does not fabricate a positive bar for zero or missing values", () => {
    expect(numericBarValue(undefined)).toBeNull();
    expect(barWidthPercent(null, 10)).toBe(0);
    expect(barWidthPercent(0, 10)).toBe(0);
    expect(barWidthPercent(5, 10)).toBe(50);
  });
});
