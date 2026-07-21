import { afterEach, describe, expect, it } from "vitest";
import { setLocale } from "../../i18n";
import en from "./evidence.en.json";
import ko from "./evidence.ko.json";
import { presentationLabel, t } from "./evidence";

afterEach(() => setLocale("en"));

function leafPaths(value: unknown, prefix = ""): string[] {
  if (typeof value === "string") return [prefix];
  if (typeof value !== "object" || value === null) return [];
  return Object.entries(value).flatMap(([key, child]) =>
    leafPaths(child, prefix === "" ? key : `${prefix}.${key}`),
  );
}

describe("evidence route localization", () => {
  it("renders the English source and interpolates values", () => {
    expect(t("evidence.audit.headlineMore", { count: 25 })).toBe(
      "25 row(s) loaded (more available)",
    );
  });

  it("provides complete Korean leaf-key coverage", () => {
    expect(leafPaths(ko).sort()).toEqual(leafPaths(en).sort());
  });

  it("resolves every route-local leaf in both locales", () => {
    const paths = leafPaths(en);
    for (const path of paths) expect(t(`evidence.${path}`)).not.toBe(`evidence.${path}`);
    setLocale("ko");
    for (const path of paths) expect(t(`evidence.${path}`)).not.toBe(`evidence.${path}`);
  });

  it("falls back to English for a missing Korean route value", () => {
    const mutableKo = ko as { common: { none?: string } };
    const original = mutableKo.common.none;
    if (original === undefined) throw new Error("Korean none value is required for this test");
    delete mutableKo.common.none;
    try {
      setLocale("ko");
      expect(t("evidence.common.none")).toBe("None");
    } finally {
      mutableKo.common.none = original;
    }
  });

  it("falls back to the main catalog for shared keys", () => {
    setLocale("ko");
    expect(t("route.audit")).not.toBe("route.audit");
  });

  it("localizes known presentation values and preserves unknown contract values", () => {
    setLocale("ko");
    expect(presentationLabel("status", "delivered")).toBe("전달됨");
    expect(presentationLabel("status", "provider_specific")).toBe("provider_specific");
  });
});
