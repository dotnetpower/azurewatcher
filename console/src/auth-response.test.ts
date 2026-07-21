import { afterEach, describe, expect, test, vi } from "vitest";

import { observeUnauthorizedApiResponses } from "./auth-response";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("API unauthorized response observer", () => {
  test("reports 401 responses from configured API roots", async () => {
    const nativeFetch = vi.fn().mockResolvedValue(new Response(null, { status: 401 }));
    const onUnauthorized = vi.fn();
    vi.stubGlobal("fetch", nativeFetch);
    const stop = observeUnauthorizedApiResponses(
      ["http://127.0.0.1:8010", "http://127.0.0.1:8011"],
      onUnauthorized,
    );

    await fetch("http://127.0.0.1:8010/live/stream");
    await fetch(new Request("http://127.0.0.1:8011/documents"));

    expect(onUnauthorized).toHaveBeenCalledTimes(2);
    stop();
    expect(globalThis.fetch).toBe(nativeFetch);
  });

  test("ignores identity-provider and non-401 responses", async () => {
    const nativeFetch = vi
      .fn()
      .mockResolvedValueOnce(new Response(null, { status: 401 }))
      .mockResolvedValueOnce(new Response(null, { status: 403 }));
    const onUnauthorized = vi.fn();
    vi.stubGlobal("fetch", nativeFetch);
    const stop = observeUnauthorizedApiResponses(
      ["http://127.0.0.1:8010"],
      onUnauthorized,
    );

    await fetch("https://login.microsoftonline.com/example/oauth2/v2.0/token");
    await fetch("http://127.0.0.1:8010/iam/self");

    expect(onUnauthorized).not.toHaveBeenCalled();
    stop();
  });
});