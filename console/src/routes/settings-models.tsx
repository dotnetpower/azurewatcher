import { useEffect, useRef, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import type { AuthContext } from "../auth";
import { DataTable, PageHeader, StatusPill } from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { t } from "../i18n";
import {
  ModelSettingsCommandError,
  saveNarratorPreference,
  saveWebSearchSettings,
} from "./settings-models.command";
import {
  DEFAULT_WEB_SEARCH_DOMAINS,
  decodeModelSettings,
  normalizeAndValidateDomains,
  type ModelCapabilityView,
  type ModelSettingsView,
  type NarratorCandidateView,
  webSearchControlsDisabled,
} from "./settings-models.model";

interface Props {
  readonly client: ReadApiClient;
  readonly auth: AuthContext;
}

export function SettingsModelsRoute({ client, auth }: Props) {
  const [view, setView] = useState<ModelSettingsView | null>(null);
  const [selection, setSelection] = useState("auto");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [webSearchEnabled, setWebSearchEnabled] = useState(true);
  const [allowedDomainsText, setAllowedDomainsText] = useState(
    DEFAULT_WEB_SEARCH_DOMAINS.join("\n"),
  );
  const [savingWebSearch, setSavingWebSearch] = useState(false);
  const [webSearchError, setWebSearchError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const loadGeneration = useRef(0);

  const applyProjection = (next: ModelSettingsView) => {
    setView(next);
    setSelection(next.narrator.requested);
    setWebSearchEnabled(next.webSearch.enabled);
    setAllowedDomainsText(next.webSearch.allowedDomains.join("\n"));
  };

  const load = async () => {
    const generation = ++loadGeneration.current;
    setLoading(true);
    setError(null);
    try {
      const next = decodeModelSettings(await client.panel<unknown>("/models/settings"));
      if (generation !== loadGeneration.current) return;
      applyProjection(next);
      setWebSearchError(null);
    } catch (reason) {
      if (generation !== loadGeneration.current) return;
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      if (generation === loadGeneration.current) setLoading(false);
    }
  };

  useEffect(() => { void load(); }, [client]);

  const save = async () => {
    loadGeneration.current += 1;
    setSaving(true);
    setError(null);
    try {
      const next = await saveNarratorPreference(
        auth,
        client.readApiBaseUrl,
        selection,
        view?.narrator.revision ?? 0,
      );
      applyProjection(next);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setSaving(false);
    }
  };

  const saveWebSearch = async () => {
    if (view === null || savingWebSearch || !view.webSearch.canManage) return;
    const validation = normalizeAndValidateDomains(allowedDomainsText, webSearchEnabled);
    setAllowedDomainsText(validation.domains.join("\n"));
    if (validation.error !== null) {
      setWebSearchError(domainValidationMessage(validation.error, validation.invalidDomains));
      return;
    }
    setSavingWebSearch(true);
    loadGeneration.current += 1;
    setWebSearchError(null);
    try {
      const next = await saveWebSearchSettings(auth, client.readApiBaseUrl, {
        enabled: webSearchEnabled,
        allowedDomains: validation.domains,
        expectedRevision: view.webSearch.revision,
      });
      applyProjection(next);
    } catch (reason) {
      if (reason instanceof ModelSettingsCommandError && reason.status === 409) {
        try {
          const latest = decodeModelSettings(await client.panel<unknown>("/models/settings"));
          applyProjection(latest);
          setWebSearchError(t("settings.models.webSearchConflict"));
        } catch {
          setWebSearchError(t("settings.models.webSearchConflictReloadFailed"));
        }
      } else {
        setWebSearchError(reason instanceof Error ? reason.message : String(reason));
      }
    } finally {
      setSavingWebSearch(false);
    }
  };

  usePublishViewContext(
    () => ({
      routeId: "settings-models",
      routeLabel: t("route.settingsModels"),
      purpose: "Resolved T1 and T2 model inventory, latency evidence, and user narrator preference.",
      glossary: composeGlossary([TERMS.tier]),
      headline: view
        ? `${view.narrator.effective} narrator preference in ${view.region ?? "unknown region"}`
        : "Model settings loading",
      capturedAt: new Date().toISOString(),
      facts: view ? [
        { key: "narrator_preference", value: view.narrator.effective, group: "models" },
        { key: "provisioning_status", value: view.provisioning.status, group: "models" },
        { key: "capability_count", value: view.capabilities.length, group: "models" },
        { key: "web_search_enabled", value: view.webSearch.enabled, group: "web_search" },
        {
          key: "web_search_allowed_domain_count",
          value: view.webSearch.allowedDomains.length,
          group: "web_search",
        },
        { key: "web_search_provider", value: view.webSearch.provider, group: "web_search" },
        {
          key: "web_search_current_model",
          value: view.webSearch.currentAutoPick ?? "unavailable",
          group: "web_search",
        },
      ] : [],
      records: {},
    }),
    [view],
  );

  return (
    <div class="stack settings-route settings-models-route">
      <PageHeader title={t("route.settingsModels")} subtitle={t("settings.models.subtitle")} />
      {loading ? <p class="muted" role="status">{t("settings.models.loading")}</p> : null}
      {error ? <div class="error" role="alert">{error}</div> : null}
      {!loading && view ? (
        <>
          <section class="settings-iam-panel" aria-labelledby="model-automation-heading">
            <header class="settings-iam-panel-head">
              <div>
                <h3 id="model-automation-heading">{t("settings.models.automation")}</h3>
                <p>{t("settings.models.automationHint")}</p>
              </div>
            </header>
            <div class="settings-access-strip settings-model-summary">
              <SummaryDatum
                label={t("settings.models.discovery")}
                value={view.discovery.automatic ? t("settings.models.automatic") : t("settings.models.manual")}
                status={view.discovery.status}
              />
              <SummaryDatum
                label={t("settings.models.provisioning")}
                value={view.provisioning.automatic ? t("settings.models.automatic") : t("settings.models.manual")}
                status={view.provisioning.status}
              />
              <SummaryDatum
                label={t("settings.models.region")}
                value={view.region ?? t("settings.models.unavailable")}
                status={view.mixedModelMode ?? t("settings.models.unavailable")}
              />
            </div>
          </section>

          <section class="settings-iam-panel" aria-labelledby="narrator-preference-heading">
            <header class="settings-iam-panel-head">
              <div>
                <h3 id="narrator-preference-heading">{t("settings.models.narratorPreference")}</h3>
                <p>{t("settings.models.narratorPreferenceHint")}</p>
              </div>
              <StatusPill kind="neutral" label={t("settings.models.perUser")} />
            </header>
            <div class="settings-model-preference-control">
              <label for="preferred-narrator-model">{t("settings.models.preferredModel")}</label>
              <select
                id="preferred-narrator-model"
                value={selection}
                onChange={(event) => setSelection(event.currentTarget.value)}
              >
                <option value="auto">{t("settings.models.autoFastest")}</option>
                {view.narrator.candidates.map((candidate) => (
                  <option key={candidate.deployment} value={candidate.deployment}>
                    {candidate.deployment}
                  </option>
                ))}
              </select>
              <button type="button" class="secondary" disabled={saving} onClick={() => { void save(); }}>
                {saving ? t("settings.models.saving") : t("settings.models.save")}
              </button>
              <small>
                {t("settings.models.effectiveModel", {
                  model: view.narrator.effective === "auto"
                    ? view.narrator.currentAutoPick ?? "Auto"
                    : view.narrator.effective,
                })}
              </small>
            </div>
            {view.narrator.fallbackReason ? (
              <div class="settings-model-fallback" role="status">{view.narrator.fallbackReason}</div>
            ) : null}
            <DataTable
              columns={candidateColumns()}
              rows={view.narrator.candidates}
              keyOf={(candidate) => candidate.deployment}
              empty={t("settings.models.noCandidates")}
            />
          </section>

          <section class="settings-iam-panel" aria-labelledby="web-search-settings-heading">
            <header class="settings-iam-panel-head">
              <div>
                <h3 id="web-search-settings-heading">{t("settings.models.webSearch")}</h3>
                <p>{t("settings.models.webSearchHint")}</p>
              </div>
              <StatusPill
                kind="neutral"
                label={view.webSearch.canManage
                  ? t("settings.models.deploymentWide")
                  : t("settings.models.ownerManaged")}
              />
            </header>
            <div class="settings-web-search-body">
              <div class="settings-web-search-toggle-row">
                <div>
                  <strong>{t("settings.models.webSearchEnabled")}</strong>
                  <small>{t("settings.models.webSearchEnabledHint")}</small>
                </div>
                <label class="settings-toggle-control">
                  <input
                    type="checkbox"
                    checked={webSearchEnabled}
                    disabled={webSearchControlsDisabled(
                      view.webSearch.canManage,
                      savingWebSearch,
                    )}
                    onChange={(event) => setWebSearchEnabled(event.currentTarget.checked)}
                  />
                  <span aria-hidden="true" />
                  <strong>
                    {webSearchEnabled ? t("settings.enabled") : t("settings.disabled")}
                  </strong>
                </label>
              </div>

              <label class="settings-domain-editor" for="web-search-allowed-domains">
                <strong>{t("settings.models.allowedDomains")}</strong>
                <small>{t("settings.models.allowedDomainsHint")}</small>
                <textarea
                  id="web-search-allowed-domains"
                  rows={8}
                  value={allowedDomainsText}
                  disabled={webSearchControlsDisabled(
                    view.webSearch.canManage,
                    savingWebSearch,
                  )}
                  onInput={(event) => setAllowedDomainsText(event.currentTarget.value)}
                  onBlur={() => setAllowedDomainsText(
                    normalizeAndValidateDomains(
                      allowedDomainsText,
                      webSearchEnabled,
                    ).domains.join("\n"),
                  )}
                />
              </label>

              <div class="settings-web-search-warning" role="note">
                {t("settings.models.webSearchBoundaryWarning")}
              </div>
              <dl class="settings-web-search-runtime">
                <div>
                  <dt>{t("settings.models.provider")}</dt>
                  <dd>{view.webSearch.provider}</dd>
                </div>
                <div>
                  <dt>{t("settings.models.currentSearchModel")}</dt>
                  <dd>{view.webSearch.currentAutoPick ?? t("settings.models.unavailable")}</dd>
                </div>
              </dl>
              {webSearchError ? (
                <div class="error settings-web-search-error" role="alert">
                  {webSearchError}
                </div>
              ) : null}
              <div class="settings-web-search-actions">
                <button
                  type="button"
                  disabled={webSearchControlsDisabled(
                    view.webSearch.canManage,
                    savingWebSearch,
                  )}
                  onClick={() => { void saveWebSearch(); }}
                >
                  {savingWebSearch
                    ? t("settings.models.savingWebSearch")
                    : t("settings.models.saveWebSearch")}
                </button>
              </div>
            </div>
          </section>

          <section class="settings-iam-panel" aria-labelledby="model-capabilities-heading">
            <header class="settings-iam-panel-head">
              <div>
                <h3 id="model-capabilities-heading">{t("settings.models.capabilities")}</h3>
                <p>{t("settings.models.capabilitiesHint")}</p>
              </div>
              <StatusPill kind="neutral" label={t("settings.models.t2Governed")} />
            </header>
            <DataTable
              columns={capabilityColumns()}
              rows={view.capabilities}
              keyOf={(capability) => capability.name}
              empty={t("settings.models.noCapabilities")}
            />
          </section>
        </>
      ) : null}
    </div>
  );
}

function domainValidationMessage(
  error: "required" | "too-many" | "invalid",
  invalidDomains: readonly string[],
): string {
  if (error === "required") return t("settings.models.domainRequired");
  if (error === "too-many") return t("settings.models.domainLimit");
  return t("settings.models.domainInvalid", { domains: invalidDomains.join(", ") });
}

function SummaryDatum({ label, value, status }: {
  readonly label: string;
  readonly value: string;
  readonly status: string;
}) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{status}</small>
    </div>
  );
}

function candidateColumns() {
  return [
    {
      key: "model",
      header: t("settings.models.model"),
      render: (item: NarratorCandidateView) => (
        <span class="settings-model-name"><strong>{item.deployment}</strong><small>{item.family ?? "-"}</small></span>
      ),
    },
    {
      key: "ttft",
      header: t("settings.models.ttft"),
      render: (item: NarratorCandidateView) => latency(item.ttftP50Ms, item.ttftP95Ms, item.ttftSamples),
    },
    {
      key: "total",
      header: t("settings.models.totalLatency"),
      render: (item: NarratorCandidateView) => latency(item.totalP50Ms, item.totalP95Ms, item.totalSamples),
    },
    {
      key: "status",
      header: t("settings.models.status"),
      render: (item: NarratorCandidateView) => <StatusPill kind="success" label={item.status} />,
    },
  ];
}

function capabilityColumns() {
  return [
    {
      key: "capability",
      header: t("settings.models.capability"),
      render: (item: ModelCapabilityView) => (
        <span class="settings-model-name"><strong>{item.name}</strong><small>{item.invocation}</small></span>
      ),
    },
    { key: "tier", header: t("settings.models.tier"), render: (item: ModelCapabilityView) => item.tier },
    {
      key: "model",
      header: t("settings.models.model"),
      render: (item: ModelCapabilityView) => item.family ?? t("settings.models.unavailable"),
    },
    {
      key: "status",
      header: t("settings.models.status"),
      render: (item: ModelCapabilityView) => (
        <StatusPill kind={item.status === "resolved" ? "success" : "warning"} label={item.status} />
      ),
    },
    {
      key: "capacity",
      header: t("settings.models.capacity"),
      render: (item: ModelCapabilityView) => `${item.capacityTpm} TPM`,
    },
  ];
}

function latency(p50: number | null, p95: number | null, samples: number) {
  if (p50 === null || p95 === null || samples === 0) {
    return <span class="muted">{t("settings.models.unavailable")}</span>;
  }
  return (
    <span class="settings-model-latency">
      <strong>{Math.round(p50)} ms</strong>
      <small>p95 {Math.round(p95)} ms · n={samples}</small>
    </span>
  );
}
