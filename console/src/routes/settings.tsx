import { useEffect, useRef, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import { PageHeader } from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { t } from "../i18n";
import {
  PREFERENCES_CHANGED_EVENT,
  readConsolePreferences,
  resetConsolePreferences,
  setConsolePreference,
  type ConsolePreferences,
} from "../preferences";
import {
  createBriefingSubscription,
  deleteConversationPolicy,
  deleteBriefingSubscription,
  deleteUserMemory,
  fetchUserContext,
  putConversationPolicy,
  putUserPreference,
  type UserContextPayload,
} from "../user-context-client";

interface Props { readonly client: ReadApiClient }

export function SettingsGeneralRoute({ client }: Props) {
  const [preferences, setPreferences] = useState<ConsolePreferences>(readConsolePreferences);
  const [serverContext, setServerContext] = useState<UserContextPayload | null>(null);
  const [contextLoading, setContextLoading] = useState(true);
  const [contextError, setContextError] = useState<string | null>(null);
  const [verbosity, setVerbosity] = useState<"concise" | "detailed">("concise");
  const [timezone, setTimezone] = useState(defaultTimezone);
  const [shareWithLearner, setShareWithLearner] = useState(false);
  const [briefingHour, setBriefingHour] = useState("07");
  const [savingContext, setSavingContext] = useState(false);
  const [pendingDeletes, setPendingDeletes] = useState<ReadonlySet<string>>(new Set());
  const refreshGeneration = useRef(0);

  useEffect(() => {
    const syncPreferences = () => setPreferences(readConsolePreferences());
    window.addEventListener(PREFERENCES_CHANGED_EVENT, syncPreferences);
    return () => window.removeEventListener(PREFERENCES_CHANGED_EVENT, syncPreferences);
  }, []);

  const refreshContext = async (): Promise<void> => {
    const generation = ++refreshGeneration.current;
    setContextLoading(true);
    try {
      const context = await fetchUserContext();
      if (generation !== refreshGeneration.current) return;
      setServerContext(context);
      setVerbosity(context.preference?.verbosity ?? "concise");
      setTimezone(context.preference?.timezone ?? defaultTimezone());
      setShareWithLearner(context.preference?.share_with_learner ?? false);
      setContextError(null);
    } catch (error) {
      if (generation !== refreshGeneration.current) return;
      setContextError(error instanceof Error ? error.message : String(error));
    } finally {
      if (generation === refreshGeneration.current) setContextLoading(false);
    }
  };

  useEffect(() => {
    void refreshContext();
  }, [client]);

  usePublishViewContext(
    () => ({
      routeId: "settings-general",
      routeLabel: t("route.settingsGeneral"),
      purpose: "Browser-local console display and accessibility preferences.",
      glossary: composeGlossary([TERMS.userPreference]),
      headline:
        `${preferences.theme} theme, ${preferences.locale} locale, ` +
        `${preferences.motion} motion, semantic verification ${preferences.semanticVerification}`,
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "theme", value: preferences.theme, group: "display" },
        { key: "locale", value: preferences.locale, group: "display" },
        { key: "motion", value: preferences.motion, group: "accessibility" },
        {
          key: "semantic_verification",
          value: preferences.semanticVerification,
          group: "verification",
        },
      ],
      records: {},
    }),
    [preferences],
  );

  const update = <Key extends keyof ConsolePreferences>(
    key: Key,
    value: ConsolePreferences[Key],
  ) => {
    setConsolePreference(key, value);
  };

  const updateLocale = (locale: ConsolePreferences["locale"]) => {
    const persisted = setConsolePreference("locale", locale);
    setLocaleOverride(persisted ? null : locale);
    window.location.reload();
  };

  const reset = () => {
    const persisted = resetConsolePreferences();
    setLocaleOverride(persisted ? null : "en");
    window.location.reload();
  };

  const openingPolicy = serverContext?.policies.find(
    (policy) => policy.kind === "opening_briefing" && policy.enabled,
  ) ?? null;
  const responsePolicy = serverContext?.policies.find(
    (policy) => policy.kind === "response_defaults" && policy.enabled,
  ) ?? null;
  const latestSourceTurnId = serverContext?.conversations.find(
    (conversation) => conversation.latest_operator_turn_id !== null,
  )?.latest_operator_turn_id ?? null;

  const saveSemanticPreferences = async (): Promise<void> => {
    if (!isValidTimezone(timezone)) {
      setContextError(t("settings.contextTimezoneInvalid"));
      return;
    }
    setSavingContext(true);
    let preferenceSaved = false;
    try {
      await putUserPreference({
        locale: preferences.locale,
        verbosity,
        timezone,
        share_with_learner: shareWithLearner,
          expected_revision: serverContext?.preference?.revision ?? 0,
      });
      preferenceSaved = true;
      if (latestSourceTurnId !== null) {
        await putConversationPolicy({
          policy_id: "response-defaults",
          kind: "response_defaults",
          source_turn_id: latestSourceTurnId,
          enabled: true,
          expected_revision: responsePolicy?.revision ?? 0,
          response_defaults: {
            verbosity,
            answer_language: preferences.locale,
          },
        });
      }
      await refreshContext();
      setContextError(null);
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      setContextError(
        preferenceSaved
          ? t("settings.contextPartialSave", { error: detail })
          : detail,
      );
    } finally {
      setSavingContext(false);
    }
  };

  const addDailyBriefing = async (): Promise<void> => {
    const hour = parseBriefingHour(briefingHour);
    if (hour === null) {
      setContextError(t("settings.briefingHourInvalid"));
      return;
    }
    if (!isValidTimezone(timezone)) {
      setContextError(t("settings.contextTimezoneInvalid"));
      return;
    }
    setSavingContext(true);
    try {
      await createBriefingSubscription({
        name: "Daily major issues",
        cron_expression: `0 ${hour} * * *`,
        timezone,
        delivery_modes: ["in_app"],
        spec: {
          kind: "major_issues",
          lookback_seconds: 86_400,
          minimum_severity: "high",
          max_items: 5,
        },
      });
      await refreshContext();
      setContextError(null);
    } catch (error) {
      setContextError(error instanceof Error ? error.message : String(error));
    } finally {
      setSavingContext(false);
    }
  };

  const enableOpeningBriefing = async (): Promise<void> => {
    if (latestSourceTurnId === null) return;
    setSavingContext(true);
    try {
      await putConversationPolicy({
        policy_id: "opening-briefing",
        kind: "opening_briefing",
        source_turn_id: latestSourceTurnId,
        enabled: true,
        expected_revision: openingPolicy?.revision ?? 0,
        briefing_spec: {
          kind: "major_issues",
          lookback_seconds: 86_400,
          minimum_severity: "high",
          max_items: 5,
          include_pending_approvals: true,
          include_failed_actions: true,
        },
      });
      await refreshContext();
      setContextError(null);
    } catch (error) {
      setContextError(error instanceof Error ? error.message : String(error));
    } finally {
      setSavingContext(false);
    }
  };

  const removeOpeningBriefing = async (): Promise<void> => {
    if (openingPolicy === null) return;
    setSavingContext(true);
    try {
      await deleteConversationPolicy(openingPolicy.policy_id, openingPolicy.revision);
      await refreshContext();
      setContextError(null);
    } catch (error) {
      setContextError(error instanceof Error ? error.message : String(error));
    } finally {
      setSavingContext(false);
    }
  };

  const removeSubscription = async (subscriptionId: string, revision: number): Promise<void> => {
    if (!window.confirm(t("settings.confirmDeleteSubscription"))) return;
    await withPendingDelete(`subscription:${subscriptionId}`, async () => {
      await deleteBriefingSubscription(subscriptionId, revision);
      await refreshContext();
    });
  };

  const removeMemory = async (memoryId: string): Promise<void> => {
    if (!window.confirm(t("settings.confirmDeleteMemory"))) return;
    await withPendingDelete(`memory:${memoryId}`, async () => {
      await deleteUserMemory(memoryId);
      await refreshContext();
    });
  };

  const withPendingDelete = async (key: string, operation: () => Promise<void>) => {
    setPendingDeletes((current) => new Set(current).add(key));
    setContextError(null);
    try {
      await operation();
    } catch (error) {
      setContextError(error instanceof Error ? error.message : String(error));
    } finally {
      setPendingDeletes((current) => {
        const next = new Set(current);
        next.delete(key);
        return next;
      });
    }
  };

  return (
    <div class="stack settings-route">
      <PageHeader title={t("route.settingsGeneral")} subtitle={t("settings.subtitle")} />

      <section class="settings-section" aria-labelledby="settings-appearance">
        <h3 id="settings-appearance">{t("settings.appearance")}</h3>
        <div class="settings-list">
          <SettingRow label={t("settings.theme")} hint={t("settings.themeHint")}>
            <SegmentedControl
              label={t("settings.theme")}
              value={preferences.theme}
              options={[
                { value: "light", label: t("settings.light") },
                { value: "dark", label: t("settings.dark") },
              ]}
              onChange={(value) => update("theme", value as ConsolePreferences["theme"])}
            />
          </SettingRow>
          <SettingRow label={t("settings.language")} hint={t("settings.languageHint")}>
            <SegmentedControl
              label={t("settings.language")}
              value={preferences.locale}
              options={[
                { value: "en", label: "English" },
                { value: "ko", label: t("settings.korean") },
              ]}
              onChange={(value) => updateLocale(value as ConsolePreferences["locale"])}
            />
          </SettingRow>
          <SettingRow label={t("settings.motion")} hint={t("settings.motionHint")}>
            <label class="settings-toggle-control">
              <input
                type="checkbox"
                checked={preferences.motion === "reduced"}
                onChange={(event) => update("motion", event.currentTarget.checked ? "reduced" : "system")}
              />
              <span aria-hidden="true" />
              <strong>{preferences.motion === "reduced" ? t("settings.reduced") : t("settings.system")}</strong>
            </label>
          </SettingRow>
        </div>
      </section>

      <section class="settings-section" aria-labelledby="settings-verification">
        <h3 id="settings-verification">{t("settings.verification")}</h3>
        <div class="settings-list">
          <SettingRow
            label={t("settings.semanticVerification")}
            hint={t("settings.semanticVerificationHint")}
          >
            <label class="settings-toggle-control">
              <input
                type="checkbox"
                checked={preferences.semanticVerification === "shadow"}
                onChange={(event) => update(
                  "semanticVerification",
                  event.currentTarget.checked ? "shadow" : "off",
                )}
              />
              <span aria-hidden="true" />
              <strong>
                {preferences.semanticVerification === "shadow"
                  ? t("settings.enabled")
                  : t("settings.disabled")}
              </strong>
            </label>
          </SettingRow>
        </div>
      </section>

      <section class="settings-section" aria-labelledby="settings-user-context">
        <h3 id="settings-user-context">{t("settings.contextTitle")}</h3>
        <p class="muted small">
          {t("settings.contextDescription")}
        </p>
        {contextError ? <p class="error-text">{contextError}</p> : null}
        {contextLoading ? <p class="muted small" role="status">{t("settings.contextLoading")}</p> : null}
        <div class="settings-list">
          <SettingRow label={t("settings.answerDetail")} hint={t("settings.answerDetailHint")}>
            <SegmentedControl
              label={t("settings.answerDetail")}
              value={verbosity}
              options={[
                { value: "concise", label: t("settings.concise") },
                { value: "detailed", label: t("settings.detailed") },
              ]}
              onChange={(value) => setVerbosity(value as "concise" | "detailed")}
            />
          </SettingRow>
          <SettingRow label={t("settings.timezone")} hint={t("settings.timezoneHint")}>
            <input
              class="form-input settings-context-input"
              value={timezone}
              placeholder="Asia/Seoul"
              onInput={(event) => setTimezone(event.currentTarget.value)}
            />
          </SettingRow>
          <SettingRow
            label={t("settings.learnerAccess")}
            hint={t("settings.learnerAccessHint")}
          >
            <label class="settings-toggle-control">
              <input
                type="checkbox"
                checked={shareWithLearner}
                onChange={(event) => setShareWithLearner(event.currentTarget.checked)}
              />
              <span aria-hidden="true" />
              <strong>{shareWithLearner ? t("settings.optedIn") : t("settings.metadataOnly")}</strong>
            </label>
          </SettingRow>
        </div>
        <div class="settings-actions">
          <button type="button" class="btn" disabled={savingContext} onClick={() => void saveSemanticPreferences()}>
            {t("settings.saveContext")}
          </button>
        </div>
      </section>

      <section class="settings-section" aria-labelledby="settings-briefings">
        <h3 id="settings-briefings">{t("settings.briefingsTitle")}</h3>
        <div class="settings-context-list">
          <article>
            <div>
              <strong>{t("settings.openingBriefing")}</strong>
              <small class="muted">
                {t("settings.openingBriefingHint")}
              </small>
            </div>
            {openingPolicy ? (
              <button
                type="button"
                class="secondary"
                disabled={savingContext}
                onClick={() => void removeOpeningBriefing()}
              >
                {t("settings.disable")}
              </button>
            ) : (
              <button
                type="button"
                class="btn"
                disabled={savingContext || latestSourceTurnId === null}
                onClick={() => void enableOpeningBriefing()}
                title={latestSourceTurnId === null ? t("settings.startConversation") : undefined}
              >
                {t("settings.enable")}
              </button>
            )}
          </article>
          {latestSourceTurnId === null && !openingPolicy ? (
            <p class="muted small">
              {t("settings.startConversationHint")}
            </p>
          ) : null}
        </div>
        <div class="settings-briefing-create">
          <label>
            <span>{t("settings.dailyHour")}</span>
            <input
              class="form-input"
              type="number"
              min="0"
              max="23"
              value={briefingHour}
              onInput={(event) => setBriefingHour(event.currentTarget.value)}
            />
          </label>
          <span class="muted small">{timezone}</span>
          <button type="button" class="btn" disabled={savingContext} onClick={() => void addDailyBriefing()}>
            {t("settings.addDailyBriefing")}
          </button>
        </div>
        <div class="settings-context-list">
          {(serverContext?.subscriptions ?? []).map((subscription) => (
            <article key={subscription.subscription_id}>
              <div>
                <strong>{subscription.name}</strong>
                <small class="muted">
                  {t("settings.subscriptionSummary", {
                    cron: subscription.cron_expression,
                    timezone: subscription.timezone,
                    next: subscription.next_run_at,
                  })}
                </small>
              </div>
              <button
                type="button"
                class="secondary"
                disabled={pendingDeletes.has(`subscription:${subscription.subscription_id}`)}
                onClick={() => void removeSubscription(
                  subscription.subscription_id,
                  subscription.revision,
                )}
              >
                {t("settings.remove")}
              </button>
            </article>
          ))}
          {!contextLoading && (serverContext?.subscriptions.length ?? 0) === 0 ? (
            <p class="muted small">{t("settings.noSubscriptions")}</p>
          ) : null}
        </div>
      </section>

      <section class="settings-section" aria-labelledby="settings-saved-memory">
        <h3 id="settings-saved-memory">{t("settings.memoryTitle")}</h3>
        <p class="muted small">
          {t("settings.memoryDescription")}
        </p>
        <div class="settings-context-list">
          {(serverContext?.memories ?? []).map((memory) => (
            <article key={memory.memory_id}>
              <div>
                <strong>{memory.category}</strong>
                <span>{memory.body}</span>
                <small class="muted">
                  {memory.expires_at
                    ? t("settings.memorySourceExpires", { source: memory.source_turn_id, expires: memory.expires_at })
                    : t("settings.memorySource", { source: memory.source_turn_id })}
                </small>
              </div>
              <button
                type="button"
                class="secondary"
                disabled={pendingDeletes.has(`memory:${memory.memory_id}`)}
                onClick={() => void removeMemory(memory.memory_id)}
              >
                {t("settings.remove")}
              </button>
            </article>
          ))}
          {!contextLoading && (serverContext?.memories.length ?? 0) === 0 ? (
            <p class="muted small">{t("settings.noMemories")}</p>
          ) : null}
        </div>
      </section>

      <section class="settings-section" aria-labelledby="settings-briefing-history">
        <h3 id="settings-briefing-history">{t("settings.recentBriefings")}</h3>
        <div class="settings-context-list">
          {(serverContext?.briefing_runs ?? []).slice(0, 10).map((run) => (
            <article key={run.run_id}>
              <div>
                <strong>{run.title}</strong>
                <span>{run.body_markdown}</span>
                <small class="muted">
                  {t("settings.briefingRunSummary", {
                    status: run.status,
                    count: run.item_count,
                    evidence: run.evidence_refs.length,
                  })}
                </small>
              </div>
            </article>
          ))}
          {!contextLoading && (serverContext?.briefing_runs.length ?? 0) === 0 ? (
            <p class="muted small">{t("settings.noBriefingRuns")}</p>
          ) : null}
        </div>
      </section>

      <div class="settings-actions">
        <button type="button" class="secondary" onClick={reset}>{t("settings.reset")}</button>
      </div>
    </div>
  );
}

export function SettingRow({ label, hint, children }: {
  readonly label: string;
  readonly hint: string;
  readonly children: preact.ComponentChildren;
}) {
  return (
    <div class="settings-row">
      <div><strong>{label}</strong><small class="muted">{hint}</small></div>
      {children}
    </div>
  );
}

export function SegmentedControl({ label, value, options, onChange }: {
  readonly label: string;
  readonly value: string;
  readonly options: readonly { readonly value: string; readonly label: string }[];
  readonly onChange: (value: string) => void;
}) {
  return (
    <div class="settings-segmented" role="group" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          class={option.value === value ? "is-active" : undefined}
          aria-pressed={option.value === value}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

function setLocaleOverride(locale: ConsolePreferences["locale"] | null): void {
  const url = new URL(window.location.href);
  if (locale === null) url.searchParams.delete("locale");
  else url.searchParams.set("locale", locale);
  window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}${url.hash}`);
}

export function defaultTimezone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
}

export function isValidTimezone(value: string): boolean {
  if (!value.trim()) return false;
  try {
    new Intl.DateTimeFormat("en", { timeZone: value.trim() }).format();
    return true;
  } catch {
    return false;
  }
}

export function parseBriefingHour(value: string): number | null {
  if (!/^\d{1,2}$/.test(value.trim())) return null;
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed >= 0 && parsed <= 23 ? parsed : null;
}
