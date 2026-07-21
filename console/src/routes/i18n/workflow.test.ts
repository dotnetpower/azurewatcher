import { afterEach, describe, expect, it } from "vitest";
import { setLocale } from "../../i18n";
import en from "./workflow.en.json";
import ko from "./workflow.ko.json";
import {
  formatCurrency,
  formatDateTime,
  formatDateTimeValue,
  formatNumber,
  statusLabel,
  t,
} from "./workflow";

afterEach(() => setLocale("en"));

function leafPaths(value: unknown, prefix = ""): string[] {
  if (typeof value === "string") return [prefix];
  if (typeof value !== "object" || value === null) return [];
  return Object.entries(value).flatMap(([key, child]) =>
    leafPaths(child, prefix === "" ? key : `${prefix}.${key}`),
  );
}

describe("workflow route localization", () => {
  it("renders the English source and interpolates values", () => {
    expect(t("workflow.builder.headlineNew", { count: 4 })).toBe(
      "Conversational workflow designer open - 4 ActionTypes available",
    );
  });

  it("provides complete Korean leaf-key coverage", () => {
    expect(leafPaths(ko).sort()).toEqual(leafPaths(en).sort());
    setLocale("ko");
    expect(t("workflow.builder.headlineNew", { count: 4 })).toBe(
      "대화형 워크플로 디자이너 열림 - 사용 가능한 ActionType 4개",
    );
  });

  it("resolves every route-local leaf in both locales", () => {
    const paths = leafPaths(en);
    for (const path of paths) expect(t(`workflow.${path}`)).not.toBe(`workflow.${path}`);
    setLocale("ko");
    for (const path of paths) expect(t(`workflow.${path}`)).not.toBe(`workflow.${path}`);
  });

  it("falls back to English for a missing Korean route value", () => {
    const mutableKo = ko as { common: { yes?: string } };
    const original = mutableKo.common.yes;
    if (original === undefined) throw new Error("Korean yes value is required for this test");
    delete mutableKo.common.yes;
    try {
      setLocale("ko");
      expect(t("workflow.common.yes")).toBe("Yes");
    } finally {
      mutableKo.common.yes = original;
    }
  });

  it("falls back to the main catalog for shared keys", () => {
    setLocale("ko");
    expect(t("route.workflowBuilder")).toBe("워크플로우 빌더");
  });

  it("formats numbers and timestamps for the active locale", () => {
    expect(formatNumber(1234567)).toBe("1,234,567");
    expect(formatDateTime("2026-07-21T00:00:00Z")).toContain("2026");
    expect(formatDateTimeValue("not-a-date")).toBe("not-a-date");
    expect(formatCurrency(1234.5, "USD")).toContain("1,234.50");
    setLocale("ko");
    expect(formatNumber(1234567)).toBe("1,234,567");
    expect(formatDateTime("2026-07-21T00:00:00Z")).toContain("2026");
    expect(statusLabel("running")).toBe("실행 중");
    expect(statusLabel("custom-status")).toBe("custom-status");
  });
});
