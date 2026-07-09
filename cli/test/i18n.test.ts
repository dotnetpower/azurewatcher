/**
 * Unit tests for the CLI i18n helper (L2 product-surface localization).
 *
 * Proves the Product i18n contract in language.instructions.md: English is the
 * source of truth, a locale catalog may lag with a mandatory English fallback,
 * and locale resolution follows preference -> FDAI_LOCALE -> en.
 */

import { afterEach, describe, expect, it } from "vitest";

import { resolveLocale, t } from "../src/i18n/index.js";

describe("i18n.t", () => {
  it("returns the English source string by default", () => {
    expect(t("tier.t0")).toBe("Handled by fixed rules");
    expect(t("tier.abstain")).toBe("Abstained");
  });

  it("returns a localized (non-English) string when the ko catalog has the key", () => {
    const localized = t("tier.t0", "ko");
    expect(localized).not.toBe(t("tier.t0", "en")); // localized, not the source
    expect(localized.length).toBeGreaterThan(0);
  });

  it("falls back to English when the ko catalog lags a key (mandatory fallback)", () => {
    // The ko catalog does not translate `tier.abstain`; the helper MUST render
    // the English source, never a blank.
    expect(t("tier.abstain", "ko")).toBe("Abstained");
  });

  it("returns the key itself when even English is missing (visible typo)", () => {
    expect(t("no.such.key")).toBe("no.such.key");
    expect(t("does.not.exist", "ko")).toBe("does.not.exist");
  });
});

describe("i18n.resolveLocale", () => {
  const original = process.env.FDAI_LOCALE;
  afterEach(() => {
    if (original === undefined) delete process.env.FDAI_LOCALE;
    else process.env.FDAI_LOCALE = original;
  });

  it("prefers an explicit preference over the environment", () => {
    process.env.FDAI_LOCALE = "en";
    expect(resolveLocale("ko-KR")).toBe("ko");
  });

  it("uses FDAI_LOCALE when no explicit preference is given", () => {
    process.env.FDAI_LOCALE = "ko";
    expect(resolveLocale()).toBe("ko");
  });

  it("defaults to en for an unknown or missing locale", () => {
    delete process.env.FDAI_LOCALE;
    expect(resolveLocale()).toBe("en");
    expect(resolveLocale("fr")).toBe("en");
  });
});
