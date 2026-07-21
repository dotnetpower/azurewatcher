import { afterEach, describe, expect, it } from "vitest";
import { setLocale } from "../../i18n";
import en from "./architecture.en.json";
import ko from "./architecture.ko.json";
import { t } from "./architecture";

afterEach(() => setLocale("en"));

function leafPaths(value: unknown, prefix = ""): string[] {
  if (typeof value === "string") return [prefix];
  if (typeof value !== "object" || value === null) return [];
  return Object.entries(value).flatMap(([key, child]) =>
    leafPaths(child, prefix === "" ? key : `${prefix}.${key}`),
  );
}

describe("architecture route localization", () => {
  it("renders the English source and interpolates values", () => {
    expect(t("architecture.filterSummary", {
      visibleResources: 2,
      totalResources: 4,
      visibleLinks: 1,
      totalLinks: 3,
    })).toBe("Showing 2 of 4 resources and 1 of 3 relationships");
  });

  it("provides complete Korean leaf-key coverage", () => {
    expect(leafPaths(ko).sort()).toEqual(leafPaths(en).sort());
    setLocale("ko");
    expect(t("architecture.filterSummary", {
      visibleResources: 2,
      totalResources: 4,
      visibleLinks: 1,
      totalLinks: 3,
    })).toBe("리소스 4개 중 2개와 관계 3개 중 1개 표시");
  });

  it("falls back to the main catalog for shared keys", () => {
    setLocale("ko");
    expect(t("route.architecture")).toBe("아키텍처");
  });
});
