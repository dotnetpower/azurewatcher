import { describe, expect, it } from "vitest";

import { withChannelLocale } from "../src/channel-context.js";

describe("withChannelLocale", () => {
  it("publishes the locale key consumed by the shared narrator", () => {
    expect(withChannelLocale("ko", { routeId: "cli-live" })).toEqual({
      routeId: "cli-live",
      _locale: "ko",
    });
  });
});
