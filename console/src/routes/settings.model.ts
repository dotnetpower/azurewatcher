import type { ConsolePreferences } from "../preferences";
import type { UserContextPayload, UserPreferencePayload } from "../user-context-client";

export interface SettingsMutationLock {
  current: boolean;
}

export function claimSettingsMutation(lock: SettingsMutationLock): boolean {
  if (lock.current) return false;
  lock.current = true;
  return true;
}

export function releaseSettingsMutation(lock: SettingsMutationLock): void {
  lock.current = false;
}

export function claimSettingsDelete(claims: Set<string>, key: string): boolean {
  if (claims.has(key)) return false;
  claims.add(key);
  return true;
}

export function contextWithSavedPreference(
  context: UserContextPayload | null,
  preference: UserPreferencePayload,
): UserContextPayload | null {
  return context === null ? null : { ...context, preference };
}

export function setLocaleOverride(locale: ConsolePreferences["locale"] | null): void {
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
