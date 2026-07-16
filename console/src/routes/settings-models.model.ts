export interface ModelCapabilityView {
  readonly name: string;
  readonly tier: "T1" | "T2";
  readonly publisher: string | null;
  readonly family: string | null;
  readonly status: string;
  readonly capacityTpm: number;
  readonly invocation: string;
  readonly reasons: readonly string[];
}

export interface NarratorCandidateView {
  readonly deployment: string;
  readonly family: string | null;
  readonly status: string;
  readonly totalP50Ms: number | null;
  readonly totalP95Ms: number | null;
  readonly totalSamples: number;
  readonly ttftP50Ms: number | null;
  readonly ttftP95Ms: number | null;
  readonly ttftSamples: number;
}

export interface WebSearchSettingsView {
  readonly enabled: boolean;
  readonly allowedDomains: readonly string[];
  readonly revision: number;
  readonly canManage: boolean;
  readonly provider: string;
  readonly currentAutoPick: string | null;
  readonly candidates: readonly unknown[];
}

export const DEFAULT_WEB_SEARCH_DOMAINS = [
  "learn.microsoft.com",
  "azure.microsoft.com",
  "nvd.nist.gov",
  "cve.org",
  "datatracker.ietf.org",
  "kubernetes.io",
  "docs.python.org",
  "postgresql.org",
] as const;

export type DomainValidationError = "required" | "too-many" | "invalid";

export interface DomainValidationResult {
  readonly domains: readonly string[];
  readonly error: DomainValidationError | null;
  readonly invalidDomains: readonly string[];
}

export interface ModelSettingsView {
  readonly region: string | null;
  readonly mixedModelMode: string | null;
  readonly discovery: {
    readonly automatic: boolean;
    readonly source: string;
    readonly status: string;
  };
  readonly provisioning: {
    readonly automatic: boolean;
    readonly status: string;
    readonly resolvedCount: number;
    readonly hilOnlyCount: number;
  };
  readonly capabilities: readonly ModelCapabilityView[];
  readonly narrator: {
    readonly requested: string;
    readonly effective: string;
    readonly fallbackReason: string | null;
    readonly currentAutoPick: string | null;
    readonly candidates: readonly NarratorCandidateView[];
  };
  readonly webSearch: WebSearchSettingsView;
  readonly t2SelectionScope: "system-governed";
}

export function decodeModelSettings(value: unknown): ModelSettingsView {
  const root = object(value, "model settings");
  const discovery = object(root["discovery"], "model settings.discovery");
  const provisioning = object(root["provisioning"], "model settings.provisioning");
  const narrator = object(root["narrator"], "model settings.narrator");
  const webSearch = object(root["web_search"], "model settings.web_search");
  const capabilities = array(root["capabilities"], "model settings.capabilities").map(
    (entry) => decodeCapability(entry),
  );
  const candidates = array(narrator["candidates"], "model settings.narrator.candidates").map(
    (entry) => decodeCandidate(entry),
  );
  const scope = string(narrator["selection_scope"], "narrator.selection_scope");
  if (scope !== "per-user") throw new Error("narrator.selection_scope MUST be per-user");
  const t2Scope = string(root["t2_selection_scope"], "t2_selection_scope");
  if (t2Scope !== "system-governed") {
    throw new Error("t2_selection_scope MUST be system-governed");
  }
  return {
    region: nullableString(root["region"], "model settings.region"),
    mixedModelMode: nullableString(root["mixed_model_mode"], "mixed_model_mode"),
    discovery: {
      automatic: boolean(discovery["automatic"], "discovery.automatic"),
      source: string(discovery["source"], "discovery.source"),
      status: string(discovery["status"], "discovery.status"),
    },
    provisioning: {
      automatic: boolean(provisioning["automatic"], "provisioning.automatic"),
      status: string(provisioning["status"], "provisioning.status"),
      resolvedCount: number(provisioning["resolved_count"], "provisioning.resolved_count"),
      hilOnlyCount: number(provisioning["hil_only_count"], "provisioning.hil_only_count"),
    },
    capabilities,
    narrator: {
      requested: string(narrator["requested"], "narrator.requested"),
      effective: string(narrator["effective"], "narrator.effective"),
      fallbackReason: nullableString(narrator["fallback_reason"], "narrator.fallback_reason"),
      currentAutoPick: nullableString(narrator["current_auto_pick"], "narrator.current_auto_pick"),
      candidates,
    },
    webSearch: {
      enabled: boolean(webSearch["enabled"], "web_search.enabled"),
      allowedDomains: array(webSearch["allowed_domains"], "web_search.allowed_domains").map(
        (domain) => string(domain, "web_search.allowed_domains[]"),
      ),
      revision: nonNegativeInteger(webSearch["revision"], "web_search.revision"),
      canManage: boolean(webSearch["can_manage"], "web_search.can_manage"),
      provider: string(webSearch["provider"], "web_search.provider"),
      currentAutoPick: nullableString(
        webSearch["current_auto_pick"],
        "web_search.current_auto_pick",
      ),
      candidates: array(webSearch["candidates"], "web_search.candidates"),
    },
    t2SelectionScope: "system-governed",
  };
}

export function normalizeAndValidateDomains(
  input: string,
  enabled: boolean,
): DomainValidationResult {
  const domains = [...new Set(
    input
      .split(/\r?\n/)
      .map((value) => value.trim().toLowerCase())
      .filter(Boolean),
  )];
  if (domains.length > 100) {
    return { domains, error: "too-many", invalidDomains: [] };
  }
  const invalidDomains = domains.filter((domain) => !isValidHost(domain));
  if (invalidDomains.length > 0) {
    return { domains, error: "invalid", invalidDomains };
  }
  if (enabled && domains.length === 0) {
    return { domains, error: "required", invalidDomains: [] };
  }
  return { domains, error: null, invalidDomains: [] };
}

export function webSearchControlsDisabled(canManage: boolean, saving: boolean): boolean {
  return !canManage || saving;
}

function isValidHost(value: string): boolean {
  if (
    value.includes("://")
    || value.includes("/")
    || value.includes(":")
    || value.includes("*")
    || /[\s?#@]/.test(value)
  ) {
    return false;
  }
  if (value.length > 253 || !value.includes(".")) return false;
  return value.split(".").every(
    (label) => /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(label),
  );
}

function decodeCapability(value: unknown): ModelCapabilityView {
  const item = object(value, "model capability");
  const tier = string(item["tier"], "model capability.tier");
  if (tier !== "T1" && tier !== "T2") throw new Error("model capability.tier is invalid");
  return {
    name: string(item["name"], "model capability.name"),
    tier,
    publisher: nullableString(item["publisher"], "model capability.publisher"),
    family: nullableString(item["family"], "model capability.family"),
    status: string(item["status"], "model capability.status"),
    capacityTpm: number(item["capacity_tpm"], "model capability.capacity_tpm"),
    invocation: string(item["invocation"], "model capability.invocation"),
    reasons: array(item["reasons"], "model capability.reasons").map((reason) =>
      string(reason, "model capability.reason")
    ),
  };
}

function decodeCandidate(value: unknown): NarratorCandidateView {
  const item = object(value, "narrator candidate");
  return {
    deployment: string(item["deployment"], "narrator candidate.deployment"),
    family: nullableString(item["family"], "narrator candidate.family"),
    status: string(item["status"], "narrator candidate.status"),
    totalP50Ms: nullableNumber(item["total_p50_ms"], "candidate.total_p50_ms"),
    totalP95Ms: nullableNumber(item["total_p95_ms"], "candidate.total_p95_ms"),
    totalSamples: number(item["total_samples"], "candidate.total_samples"),
    ttftP50Ms: nullableNumber(item["ttft_p50_ms"], "candidate.ttft_p50_ms"),
    ttftP95Ms: nullableNumber(item["ttft_p95_ms"], "candidate.ttft_p95_ms"),
    ttftSamples: number(item["ttft_samples"], "candidate.ttft_samples"),
  };
}

function object(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${label} MUST be an object`);
  }
  return value as Record<string, unknown>;
}

function array(value: unknown, label: string): readonly unknown[] {
  if (!Array.isArray(value)) throw new Error(`${label} MUST be an array`);
  return value;
}

function string(value: unknown, label: string): string {
  if (typeof value !== "string") throw new Error(`${label} MUST be a string`);
  return value;
}

function nullableString(value: unknown, label: string): string | null {
  if (value === null || value === undefined) return null;
  return string(value, label);
}

function number(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`${label} MUST be a finite number`);
  }
  return value;
}

function nullableNumber(value: unknown, label: string): number | null {
  if (value === null || value === undefined) return null;
  return number(value, label);
}

function nonNegativeInteger(value: unknown, label: string): number {
  const parsed = number(value, label);
  if (!Number.isInteger(parsed) || parsed < 0) {
    throw new Error(`${label} MUST be a non-negative integer`);
  }
  return parsed;
}

function boolean(value: unknown, label: string): boolean {
  if (typeof value !== "boolean") throw new Error(`${label} MUST be a boolean`);
  return value;
}
