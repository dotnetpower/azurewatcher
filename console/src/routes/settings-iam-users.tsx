import { useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import { DataTable, StatusPill } from "../components/ui";
import { t } from "../i18n";
import type {
  HumanIdentityResult,
  IamRole,
  IdentityRosterItem,
} from "./settings-iam.model";

type RosterFilter = "all" | "person" | "group";
type AssignableRole = Exclude<IamRole, "BreakGlass">;

const ASSIGNABLE_ROLES: readonly AssignableRole[] = [
  "Reader",
  "Contributor",
  "Approver",
  "Owner",
];

interface Props {
  readonly client: ReadApiClient;
  readonly canManage: boolean;
  readonly roster: readonly IdentityRosterItem[];
  readonly referencedUsers: readonly IdentityRosterItem[];
  readonly onAssign: (
    identity: IdentityRosterItem | HumanIdentityResult,
    role: AssignableRole,
  ) => Promise<void>;
}

export function DirectoryUserSearch({
  client,
  canManage,
  roster,
  referencedUsers,
  onAssign,
}: Props) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<readonly HumanIdentityResult[]>([]);
  const [filter, setFilter] = useState<RosterFilter>("all");
  const [searching, setSearching] = useState(false);
  const [pendingSubject, setPendingSubject] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (!canManage) {
    return <LockedIamPanel message={t("settings.iam.usersOwnerOnly")} />;
  }

  const search = async (event: SubmitEvent) => {
    event.preventDefault();
    setSearching(true);
    setError(null);
    try {
      setResults(await client.searchIamUsers(query));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      setResults([]);
    } finally {
      setSearching(false);
    }
  };

  const assign = async (
    identity: IdentityRosterItem | HumanIdentityResult,
    role: AssignableRole,
  ) => {
    setPendingSubject(identity.subjectId);
    setError(null);
    try {
      await onAssign(identity, role);
      if ("userType" in identity) setResults([]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setPendingSubject(null);
    }
  };

  const source = roster.length > 0 ? roster : referencedUsers;
  const visibleRoster = source.filter(
    (item) => filter === "all" || item.principalType === filter,
  );

  return (
    <div class="settings-iam-panel settings-users-panel">
      <header class="settings-iam-panel-head">
        <div>
          <h3>{t("settings.iam.directoryRoster")}</h3>
          <p>{t("settings.iam.directoryRosterHint")}</p>
        </div>
        <div class="settings-roster-counts">
          <StatusPill kind="neutral" label={t("settings.iam.peopleCount", {
            count: source.filter((item) => item.principalType === "person").length,
          })} />
          <StatusPill kind="neutral" label={t("settings.iam.groupsCount", {
            count: source.filter((item) => item.principalType === "group").length,
          })} />
        </div>
      </header>

      <div class="settings-user-picker">
        <form class="settings-directory-search-form" onSubmit={search}>
          <label for="iam-user-search">{t("settings.iam.addByAlias")}</label>
          <div>
            <input
              id="iam-user-search"
              type="search"
              minLength={2}
              maxLength={128}
              required
              value={query}
              placeholder={t("settings.iam.aliasPlaceholder")}
              onInput={(event) => setQuery(event.currentTarget.value)}
            />
            <button type="submit" disabled={searching}>
              {searching ? t("settings.iam.searching") : t("settings.iam.search")}
            </button>
          </div>
        </form>
        {results.length > 0 ? (
          <div class="settings-search-results">
            {results.map((identity) => (
              <div key={`${identity.provider}:${identity.subjectId}`}>
                <PrincipalLabel
                  displayName={identity.displayName}
                  secondary={identity.username}
                  type="person"
                />
                <RoleDropdown
                  label={t("settings.iam.selectRoleAndAdd")}
                  disabled={!identity.active || pendingSubject === identity.subjectId}
                  onSelect={(role) => { void assign(identity, role); }}
                />
              </div>
            ))}
          </div>
        ) : null}
        {error ? <div class="error" role="alert">{error}</div> : null}
      </div>

      <div class="settings-roster-toolbar" role="group" aria-label={t("settings.iam.rosterFilter")}>
        {(["all", "person", "group"] as const).map((value) => (
          <button
            key={value}
            type="button"
            class={filter === value ? "is-active" : undefined}
            aria-pressed={filter === value}
            onClick={() => setFilter(value)}
          >
            {t(`settings.iam.rosterFilterValue.${value}`)}
          </button>
        ))}
      </div>

      <DataTable
        columns={[
          {
            key: "principal",
            header: t("settings.iam.principal"),
            render: (item: IdentityRosterItem) => (
              <PrincipalLabel
                displayName={item.displayName}
                secondary={item.username ?? item.subjectId}
                type={item.principalType}
              />
            ),
          },
          {
            key: "type",
            header: t("settings.iam.type"),
            render: (item: IdentityRosterItem) => (
              t(`settings.iam.principalType.${item.principalType}`)
            ),
          },
          {
            key: "roles",
            header: t("settings.iam.currentRoles"),
            render: (item: IdentityRosterItem) => (
              <span class="settings-role-list">
                {item.roles.map((role) => (
                  <StatusPill key={role} kind="neutral" label={role} />
                ))}
              </span>
            ),
          },
          {
            key: "change",
            header: t("settings.iam.changeRole"),
            render: (item: IdentityRosterItem) => (
              <RoleDropdown
                label={t("settings.iam.changeRole")}
                disabled={!item.active || pendingSubject === item.subjectId}
                onSelect={(role) => { void assign(item, role); }}
              />
            ),
          },
        ]}
        rows={visibleRoster}
        keyOf={(item) => `${item.provider}:${item.subjectId}`}
        empty={t("settings.iam.noRosterEntries")}
      />
    </div>
  );
}

function RoleDropdown({ label, disabled, onSelect }: {
  readonly label: string;
  readonly disabled: boolean;
  readonly onSelect: (role: AssignableRole) => void;
}) {
  return (
    <select
      class="settings-role-select"
      aria-label={label}
      disabled={disabled}
      value=""
      onChange={(event) => {
        const role = event.currentTarget.value as AssignableRole;
        if (role) onSelect(role);
      }}
    >
      <option value="">{label}</option>
      {ASSIGNABLE_ROLES.map((role) => <option key={role} value={role}>{role}</option>)}
    </select>
  );
}

function PrincipalLabel({ displayName, secondary, type }: {
  readonly displayName: string;
  readonly secondary: string;
  readonly type: "person" | "group";
}) {
  return (
    <span class="settings-principal-label">
      <span class="settings-principal-icon" aria-hidden="true">
        {type === "group" ? <GroupIcon /> : <PersonIcon />}
      </span>
      <span><strong>{displayName}</strong><small>{secondary}</small></span>
    </span>
  );
}

function LockedIamPanel({ message }: { readonly message: string }) {
  return (
    <div class="settings-locked-panel">
      <LockIcon />
      <strong>{t("settings.iam.restricted")}</strong>
      <p>{message}</p>
    </div>
  );
}

function PersonIcon() {
  return <svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="3" /><path d="M5 20c0-4 3-7 7-7s7 3 7 7" /></svg>;
}

function GroupIcon() {
  return <svg viewBox="0 0 24 24"><circle cx="9" cy="8" r="3" /><circle cx="17" cy="10" r="2" /><path d="M3 20c0-4 3-7 6-7s6 3 6 7M14 15c3 0 5 2 5 5" /></svg>;
}

function LockIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="10" width="14" height="10" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3" /></svg>;
}
