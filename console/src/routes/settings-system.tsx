import type { ReadApiClient } from "../api";
import type { AuthContext } from "../auth";
import { useEffect, useState } from "preact/hooks";
import { PageHeader, StatusPill } from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { t } from "../i18n";
import { SettingRow } from "./settings";

interface Props {
  readonly client: ReadApiClient;
  readonly auth: AuthContext;
}

export function SettingsIntegrationsRoute({ auth }: Props) {
  const authMode = authenticationMode(auth);

  usePublishViewContext(
    () => ({
      routeId: "settings-integrations",
      routeLabel: t("route.settingsIntegrations"),
      purpose: "Read-only connection status for identity, delivery, and operator integrations.",
      glossary: composeGlossary([TERMS.humanRbac]),
      headline: `Authentication mode: ${authMode}`,
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "authentication_mode", value: authMode, group: "identity" },
      ],
      records: {},
    }),
    [authMode],
  );

  return (
    <div class="stack settings-route">
      <PageHeader
        title={t("route.settingsIntegrations")}
        subtitle={t("settings.integrationsSubtitle")}
      />
      <section class="settings-section" aria-labelledby="settings-identity-integration">
        <h3 id="settings-identity-integration">{t("settings.identity")}</h3>
        <div class="settings-list">
          <SettingRow label={t("settings.entra")} hint={t("settings.entraHint")}>
            <StatusPill kind="neutral" label={authMode} />
          </SettingRow>
        </div>
      </section>
      <section class="settings-section" aria-labelledby="settings-delivery-integrations">
        <h3 id="settings-delivery-integrations">{t("settings.delivery")}</h3>
        <div class="settings-list">
          <SettingRow label={t("settings.githubApp")} hint={t("settings.githubAppHint")}>
            <StatusPill kind="neutral" label={t("settings.statusUnknown")} />
          </SettingRow>
          <SettingRow label={t("settings.teams")} hint={t("settings.teamsHint")}>
            <StatusPill kind="neutral" label={t("settings.statusUnknown")} />
          </SettingRow>
        </div>
      </section>
    </div>
  );
}

export function SettingsDiagnosticsRoute({ client, auth }: Props) {
  const authMode = authenticationMode(auth);
  const [health, setHealth] = useState<"checking" | "available" | "unavailable">("checking");
  const [healthError, setHealthError] = useState<string | null>(null);

  const checkHealth = async () => {
    setHealth("checking");
    setHealthError(null);
    try {
      const result = await client.panel<unknown>("/healthz");
      if (!isHealthy(result)) throw new Error("Health response was invalid");
      setHealth("available");
    } catch (reason) {
      setHealth("unavailable");
      setHealthError(reason instanceof Error ? reason.message : String(reason));
    }
  };

  useEffect(() => { void checkHealth(); }, [client]);

  usePublishViewContext(
    () => ({
      routeId: "settings-diagnostics",
      routeLabel: t("route.settingsDiagnostics"),
      purpose: "Read-only runtime and authentication diagnostics for this console session.",
      glossary: composeGlossary([TERMS.humanRbac]),
      headline: `Runtime health: ${health}; authentication mode: ${authMode}`,
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "read_api_health", value: health, group: "runtime" },
        { key: "authentication_mode", value: authMode, group: "identity" },
      ],
      records: {},
    }),
    [authMode, health],
  );

  return (
    <div class="stack settings-route">
      <PageHeader
        title={t("route.settingsDiagnostics")}
        subtitle={t("settings.diagnosticsSubtitle")}
      />
      <section class="settings-section" aria-labelledby="settings-runtime">
        <h3 id="settings-runtime">{t("settings.runtime")}</h3>
        <div class="settings-list">
          <SettingRow label={t("settings.readApi")} hint={t("settings.readApiHint")}>
            <span class="settings-diagnostic-action">
              <StatusPill
                kind={health === "available" ? "success" : health === "unavailable" ? "danger" : "neutral"}
                label={t(`settings.health.${health}`)}
              />
              <button type="button" disabled={health === "checking"} onClick={() => { void checkHealth(); }}>
                {t("settings.retry")}
              </button>
            </span>
          </SettingRow>
          <SettingRow label={t("settings.authentication")} hint={t("settings.authenticationHint")}>
            <code class="settings-runtime-value">{authMode}</code>
          </SettingRow>
          <SettingRow label={t("settings.principal")} hint={t("settings.principalHint")}>
            <code class="settings-runtime-value">{auth.account?.username ?? t("settings.unavailable")}</code>
          </SettingRow>
        </div>
      </section>
      {healthError ? <div class="error" role="alert">{healthError}</div> : null}
    </div>
  );
}

export function isHealthy(value: unknown): boolean {
  return typeof value === "object"
    && value !== null
    && !Array.isArray(value)
    && (value as Record<string, unknown>)["status"] === "ok";
}

function authenticationMode(auth: AuthContext): string {
  if (auth.localAzureCli) return "Azure CLI";
  if (auth.devMode) return "Development";
  return "Microsoft Entra ID";
}
