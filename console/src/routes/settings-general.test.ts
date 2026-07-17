import { describe, expect, it } from "vitest";
import { contextWithSavedPreference, isValidTimezone, parseBriefingHour } from "./settings";

describe("General Settings validation", () => {
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
