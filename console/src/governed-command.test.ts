import { afterEach, describe, expect, it, vi } from "vitest";
import type { AuthContext } from "./auth";
import { GovernedCommandError, putGovernedJson } from "./governed-command";

const auth: AuthContext = {
  devMode: false,
  account: null,
  getAuthorizationHeader: async () => "Bearer token",
  signIn: async () => undefined,
  signOut: async () => undefined,
};

afterEach(() => vi.unstubAllGlobals());

describe("governed command client", () => {
  it.each([
    [{ detail: "plain detail" }, "plain detail"],
    [{ error: { message: "production envelope" } }, "production envelope"],
  ])("preserves server error envelope %#", async (payload, message) => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(payload), {
      status: 409,
      headers: { "content-type": "application/json" },
    })));

    await expect(putGovernedJson(auth, "http://127.0.0.1:8030", "/write", {}))
      .rejects.toEqual(new GovernedCommandError(message, 409));
  });

  it("sends the bearer token and decodes JSON", async () => {
    const fetchMock = vi.fn(async (_url: URL, init?: RequestInit) => {
      expect((init?.headers as Record<string, string>).authorization).toBe("Bearer token");
      expect(init?.signal).toBeInstanceOf(AbortSignal);
      return new Response(JSON.stringify({ saved: true }), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(putGovernedJson(auth, "http://127.0.0.1:8030", "/write", {}))
      .resolves.toEqual({ saved: true });
  });
});
