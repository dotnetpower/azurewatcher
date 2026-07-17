import { afterEach, describe, expect, test } from "vitest";
import { setLocale } from "./i18n";
import { formatConsoleTimestamp } from "./time-format";

afterEach(() => setLocale("en"));

describe("console evidence timestamps", () => {
  test("distinguishes missing, malformed, and valid timestamps", () => {
    expect(formatConsoleTimestamp(null)).toBe("-");
    expect(formatConsoleTimestamp(null, "Unavailable")).toBe("Unavailable");
    expect(formatConsoleTimestamp("not-a-timestamp")).toBe("not-a-timestamp");
    expect(formatConsoleTimestamp("2026-07-17T08:00:00Z")).toMatch(/2026/);
  });

  test("uses the active product locale", () => {
    setLocale("ko");
    expect(formatConsoleTimestamp("2026-07-17T08:00:00Z")).toMatch(/2026/);
  });
});
