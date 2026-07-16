import { afterEach, describe, expect, it, vi } from "vitest";
import type { AuthContext } from "../auth";
import {
  saveNarratorPreference,
  saveWebSearchSettings,
} from "./settings-models.command";
import {
  DEFAULT_WEB_SEARCH_DOMAINS,
  decodeModelSettings,
  normalizeAndValidateDomains,
  webSearchControlsDisabled,
} from "./settings-models.model";

const payload = {
  region: "example-region",
  mixed_model_mode: "hil-only",
  discovery: { automatic: true, source: "rule-catalog/llm-registry.yaml", status: "enabled" },
  provisioning: { automatic: true, status: "degraded", resolved_count: 1, hil_only_count: 1 },
  capabilities: [{
    name: "t1.judge",
    tier: "T1",
    publisher: "OpenAI",
    family: "gpt-mini",
    status: "resolved",
    capacity_tpm: 1000,
    invocation: "always",
    reasons: [],
    user_selectable: false,
  }],
  narrator: {
    selection_scope: "per-user",
    revision: 1,
    requested: "auto",
    effective: "auto",
    fallback_reason: null,
    current_auto_pick: "narrator-fast",
    candidates: [{
      deployment: "narrator-fast",
      family: "gpt-fast",
      status: "available",
      total_p50_ms: 800,
      total_p95_ms: 1200,
      total_samples: 8,
      ttft_p50_ms: 220,
      ttft_p95_ms: 410,
      ttft_samples: 5,
    }],
  },
  web_search: {
    enabled: true,
    allowed_domains: [...DEFAULT_WEB_SEARCH_DOMAINS],
    revision: 1,
    can_manage: true,
    provider: "azure-responses",
    current_auto_pick: "narrator-fast",
    candidates: [],
  },
  t2_selection_scope: "system-governed",
};

afterEach(() => vi.unstubAllGlobals());

describe("Settings Models contracts", () => {
  it("decodes true TTFT separately from total latency", () => {
    const decoded = decodeModelSettings(payload);

    expect(decoded.narrator.candidates[0]?.ttftP50Ms).toBe(220);
    expect(decoded.narrator.candidates[0]?.totalP50Ms).toBe(800);
    expect(decoded.t2SelectionScope).toBe("system-governed");
    expect(decoded.webSearch.enabled).toBe(true);
    expect(decoded.webSearch.allowedDomains).toEqual(DEFAULT_WEB_SEARCH_DOMAINS);
    expect(decoded.webSearch.revision).toBe(1);
  });

  it.each([
    ["enabled", { ...payload.web_search, enabled: "yes" }],
    ["domains", { ...payload.web_search, allowed_domains: "learn.microsoft.com" }],
    ["revision", { ...payload.web_search, revision: 1.5 }],
  ])("rejects malformed web-search %s", (_label, webSearch) => {
    expect(() => decodeModelSettings({ ...payload, web_search: webSearch })).toThrow();
  });

  it("saves the authenticated user's narrator preference", async () => {
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
      expect(JSON.parse(String(init?.body))).toEqual({
        preferred_narrator_model: "narrator-fast",
        expected_revision: 1,
      });
      expect((init?.headers as Record<string, string>).authorization).toBe("Bearer token");
      return new Response(JSON.stringify({
        ...payload,
        narrator: { ...payload.narrator, requested: "narrator-fast", effective: "narrator-fast" },
      }), { status: 200, headers: { "content-type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetchMock);
    const auth: AuthContext = {
      devMode: false,
      account: null,
      getAuthorizationHeader: async () => "Bearer token",
      signIn: async () => undefined,
      signOut: async () => undefined,
    };

    const saved = await saveNarratorPreference(
      auth,
      "http://127.0.0.1:8030",
      "narrator-fast",
      1,
    );

    expect(saved.narrator.effective).toBe("narrator-fast");
  });

  it("saves deployment-global web-search settings with revision", async () => {
    const fetchMock = vi.fn(async (url: string | URL, init?: RequestInit) => {
      expect(String(url)).toBe("http://127.0.0.1:8030/models/web-search-settings");
      expect(JSON.parse(String(init?.body))).toEqual({
        enabled: true,
        allowed_domains: ["learn.microsoft.com"],
        expected_revision: 1,
      });
      expect((init?.headers as Record<string, string>).authorization).toBe("Bearer token");
      return new Response(JSON.stringify(payload), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    const auth: AuthContext = {
      devMode: false,
      account: null,
      getAuthorizationHeader: async () => "Bearer token",
      signIn: async () => undefined,
      signOut: async () => undefined,
    };

    await saveWebSearchSettings(auth, "http://127.0.0.1:8030", {
      enabled: true,
      allowedDomains: ["learn.microsoft.com"],
      expectedRevision: 1,
    });

    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("normalizes domains and removes duplicates and blank lines", () => {
    const result = normalizeAndValidateDomains(
      " Learn.Microsoft.com \n\nlearn.microsoft.com\n NVD.NIST.GOV ",
      true,
    );

    expect(result).toEqual({
      domains: ["learn.microsoft.com", "nvd.nist.gov"],
      error: null,
      invalidDomains: [],
    });
  });

  it.each([
    "https://learn.microsoft.com/path",
    "learn.microsoft.com/path",
    "learn.microsoft.com:443",
    "*.microsoft.com",
  ])("rejects non-host domain input %s", (domain) => {
    const result = normalizeAndValidateDomains(domain, true);
    expect(result.error).toBe("invalid");
    expect(result.invalidDomains).toEqual([domain]);
  });

  it("requires at least one domain only while enabled", () => {
    expect(normalizeAndValidateDomains("", true).error).toBe("required");
    expect(normalizeAndValidateDomains("", false).error).toBeNull();
  });

  it("rejects more than 100 unique hosts", () => {
    const domains = Array.from({ length: 101 }, (_, index) => `host-${index}.example.com`);
    expect(normalizeAndValidateDomains(domains.join("\n"), true).error).toBe("too-many");
  });

  it("preserves the 409 status for conflict reload handling", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(
      JSON.stringify({ detail: "revision conflict" }),
      { status: 409, headers: { "content-type": "application/json" } },
    )));
    const auth: AuthContext = {
      devMode: false,
      account: null,
      getAuthorizationHeader: async () => "Bearer token",
      signIn: async () => undefined,
      signOut: async () => undefined,
    };

    await expect(saveWebSearchSettings(auth, "http://127.0.0.1:8030", {
      enabled: true,
      allowedDomains: ["learn.microsoft.com"],
      expectedRevision: 1,
    })).rejects.toMatchObject({
      status: 409,
      message: "revision conflict",
    });
  });

  it("disables controls for non-owners and while saving", () => {
    expect(webSearchControlsDisabled(false, false)).toBe(true);
    expect(webSearchControlsDisabled(true, true)).toBe(true);
    expect(webSearchControlsDisabled(true, false)).toBe(false);
  });

  it.each([
    { ...payload, provisioning: { ...payload.provisioning, resolved_count: -1 } },
    {
      ...payload,
      narrator: {
        ...payload.narrator,
        candidates: [{ ...payload.narrator.candidates[0], ttft_p50_ms: -1 }],
      },
    },
    { ...payload, discovery: { ...payload.discovery, status: "unknown" } },
  ])("rejects invalid model metrics or statuses %#", (value) => {
    expect(() => decodeModelSettings(value)).toThrow();
  });
});
