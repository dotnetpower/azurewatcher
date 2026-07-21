import { afterEach, describe, expect, it } from "vitest";
import { setLocale } from "../../i18n";
import en from "./ontology.en.json";
import ko from "./ontology.ko.json";
import { formatDateTime, formatNumber, t } from "./ontology";

afterEach(() => setLocale("en"));

function leafPaths(value: unknown, prefix = ""): string[] {
  if (typeof value === "string") return [prefix];
  if (typeof value !== "object" || value === null) return [];
  return Object.entries(value).flatMap(([key, child]) =>
    leafPaths(child, prefix === "" ? key : `${prefix}.${key}`),
  );
}

describe("ontology route localization", () => {
  it("renders the English source and interpolates values", () => {
    expect(t("ontology.context.ontologyHeadline", {
      objects: 2,
      links: 3,
      actions: 4,
    })).toBe("2 ObjectTypes - 3 LinkTypes - 4 ActionTypes");
  });

  it("provides complete Korean leaf-key coverage", () => {
    expect(leafPaths(ko).sort()).toEqual(leafPaths(en).sort());
    setLocale("ko");
    expect(t("ontology.context.ontologyHeadline", {
      objects: 2,
      links: 3,
      actions: 4,
    })).toBe("ObjectType 2개 - LinkType 3개 - ActionType 4개");
  });

  it("resolves every route-local leaf in both locales", () => {
    const paths = leafPaths(en);
    for (const path of paths) {
      const key = `ontology.${path}`;
      expect(t(key)).not.toBe(key);
    }
    setLocale("ko");
    for (const path of paths) {
      const key = `ontology.${path}`;
      expect(t(key)).not.toBe(key);
    }
  });

  it("falls back to English for a missing Korean route value", () => {
    const mutableKo = ko as { common: { yes?: string } };
    const original = mutableKo.common.yes;
    if (original === undefined) throw new Error("Korean yes value is required for this test");
    delete mutableKo.common.yes;
    try {
      setLocale("ko");
      expect(t("ontology.common.yes")).toBe("Yes");
    } finally {
      mutableKo.common.yes = original;
    }
  });

  it("falls back to the main catalog for shared keys", () => {
    setLocale("ko");
    expect(t("route.ontology")).toBe("온톨로지");
  });

  it("formats numbers and timestamps for the active locale", () => {
    expect(formatNumber(1234567)).toBe("1,234,567");
    expect(formatDateTime("2026-07-21T00:00:00Z")).toContain("2026");
    setLocale("ko");
    expect(formatNumber(1234567)).toBe("1,234,567");
    expect(formatDateTime("2026-07-21T00:00:00Z")).toContain("2026");
  });
});
