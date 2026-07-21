import { describe, expect, it } from "vitest";
import {
  claimSettingsDelete,
  claimSettingsMutation,
  contextWithSavedPreference,
  isValidTimezone,
  parseBriefingHour,
  releaseSettingsMutation,
} from "./settings";

describe("General Settings validation", () => {
  it("claims one context mutation synchronously", () => {
    const lock = { current: false };
    expect(claimSettingsMutation(lock)).toBe(true);
    expect(claimSettingsMutation(lock)).toBe(false);
    releaseSettingsMutation(lock);
    expect(claimSettingsMutation(lock)).toBe(true);
  });

  it("deduplicates pending deletes by resource key", () => {
    const claims = new Set<string>();
    expect(claimSettingsDelete(claims, "memory:one")).toBe(true);
    expect(claimSettingsDelete(claims, "memory:one")).toBe(false);
    expect(claimSettingsDelete(claims, "memory:two")).toBe(true);
  });

  it("keeps the successful preference revision after a later partial-save failure", () => {
    const context = {
      preference: { revision: 3 },
      memories: [],
      policies: [],
      subscriptions: [],
      conversations: [],
    } as never;
    const saved = { revision: 4 } as never;
    expect(contextWithSavedPreference(context, saved)?.preference?.revision).toBe(4);
  });

  it("accepts valid IANA timezones", () => {
    expect(isValidTimezone("UTC")).toBe(true);
    expect(isValidTimezone("Asia/Seoul")).toBe(true);
  });

  it("rejects invalid or empty timezones", () => {
    expect(isValidTimezone("")).toBe(false);
    expect(isValidTimezone("Not/A_Real_Zone")).toBe(false);
  });

  it.each([
    ["0", 0],
    ["07", 7],
    ["23", 23],
  ])("parses valid briefing hour %s", (value, expected) => {
    expect(parseBriefingHour(value)).toBe(expected);
  });

  it.each(["", "7.5", "-1", "24", "abc"])("rejects invalid briefing hour %s", (value) => {
    expect(parseBriefingHour(value)).toBeNull();
  });
});
