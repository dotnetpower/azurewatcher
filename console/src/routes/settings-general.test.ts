import { describe, expect, it } from "vitest";
import { isValidTimezone, parseBriefingHour } from "./settings";

describe("General Settings validation", () => {
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
