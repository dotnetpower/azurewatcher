import { describe, expect, test, vi } from "vitest";
import {
  clearLocalAuthBypass,
  enableLocalAuthBypass,
  establishLocalAuthBypass,
  readLocalAuthBypass,
} from "./local-auth-session";

function storage() {
  const values = new Map<string, string>();
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => { values.set(key, value); },
    removeItem: (key: string) => { values.delete(key); },
  };
}

describe("local auth bypass session", () => {
  test("enables and clears bypass in session-scoped storage", () => {
    const session = storage();

    expect(readLocalAuthBypass(session)).toBe(false);
    expect(enableLocalAuthBypass(session)).toBe(true);
    expect(readLocalAuthBypass(session)).toBe(true);
    expect(clearLocalAuthBypass(session)).toBe(true);
    expect(readLocalAuthBypass(session)).toBe(false);
  });

  test("fails closed when storage is unavailable", () => {
    const unavailable = {
      getItem: vi.fn(() => { throw new Error("blocked"); }),
      setItem: vi.fn(() => { throw new Error("blocked"); }),
      removeItem: vi.fn(() => { throw new Error("blocked"); }),
    };

    expect(readLocalAuthBypass(unavailable)).toBe(false);
    expect(enableLocalAuthBypass(unavailable)).toBe(false);
    expect(clearLocalAuthBypass(unavailable)).toBe(false);
  });

  test("persists bypass only after anonymous API access succeeds", async () => {
    const session = storage();
    const probe = vi.fn(async () => undefined);

    await establishLocalAuthBypass(probe, session);

    expect(probe).toHaveBeenCalledOnce();
    expect(readLocalAuthBypass(session)).toBe(true);
  });

  test("does not persist bypass when the API requires authentication", async () => {
    const session = storage();

    await expect(establishLocalAuthBypass(
      async () => { throw new Error("HTTP 401"); },
      session,
    )).rejects.toThrow("HTTP 401");
    expect(readLocalAuthBypass(session)).toBe(false);
  });
});
