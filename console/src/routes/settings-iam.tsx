import { useEffect, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import type { AuthContext } from "../auth";
import { DataTable, PageHeader, StatusPill, type PillKind } from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { t } from "../i18n";
import { AccessRequestsView } from "./settings-iam-requests";
import { DirectoryUserSearch } from "./settings-iam-users";
import { submitIamAccessRequest } from "./settings-iam.command";
import type {
  HumanIdentityResult,
  IamAccessRequest,
  IamOverview,
  IamRole,
  IamRoleDefinition,
  IdentityRosterItem,
} from "./settings-iam.model";

interface Props {
  readonly client: ReadApiClient;
  readonly auth: AuthContext;
}

type IamTab = "my-access" | "users" | "roles" | "requests";

export function SettingsIamRoute({ client, auth }: Props) {
  const [tab, setTab] = useState<IamTab>("my-access");
  const [overview, setOverview] = useState<IamOverview | null>(null);
  const [requests, setRequests] = useState<readonly IamAccessRequest[]>([]);
  const [roster, setRoster] = useState<readonly IdentityRosterItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const nextOverview = await client.iamOverview();
      setOverview(nextOverview);
      const manager = nextOverview.principal.capabilities.includes("manage-group-membership");
      if (manager) {
        const [nextRequests, nextRoster] = await Promise.all([
          client.listIamAccessRequests(),
          client.iamRoster(),
        ]);
        setRequests(nextRequests);
        setRoster(nextRoster);
      } else {
        setRequests([]);
        setRoster([]);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, [client]);

  const username = auth.account?.username ?? t("settings.unavailable");
  const roles = overview?.principal.roles ?? currentTokenRoles(auth);
  const canManage = overview?.principal.capabilities.includes("manage-group-membership") ?? false;

  const selectTab = (nextTab: IamTab) => {
    setTab(nextTab);
    if (nextTab === "users" || nextTab === "requests") {
      void load();
    }
  };

  usePublishViewContext(
    () => ({
      routeId: "settings-iam",
      routeLabel: t("route.settingsIam"),
      purpose: "Human identity roles, effective capabilities, and governed access requests.",
      glossary: composeGlossary([TERMS.humanRbac]),
      headline: `${username}: ${roles.join(", ") || "unassigned"}`,
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "principal", value: username, group: "identity" },
        { key: "roles", value: roles.join(",") || "unassigned", group: "identity" },
        { key: "access_request_count", value: requests.length, group: "identity" },
      ],
      records: {},
    }),
    [requests.length, roles, username],
  );

  return (
    <div class="stack settings-route">
      <PageHeader title={t("route.settingsIam")} subtitle={t("settings.iam.subtitle")} />
      <nav class="settings-tabs" aria-label={t("settings.iam.tabsLabel")}>
        {([
          ["my-access", t("settings.iam.myAccess")],
          ["users", t("settings.iam.users")],
          ["roles", t("settings.iam.roles")],
          ["requests", t("settings.iam.requests")],
        ] as const).map(([id, label]) => (
          <button
            key={id}
            type="button"
            class={tab === id ? "is-active" : undefined}
            aria-pressed={tab === id}
            onClick={() => selectTab(id)}
          >
            {label}
          </button>
        ))}
      </nav>

      {loading ? <p class="muted" role="status">{t("settings.iam.loading")}</p> : null}
      {error ? <div class="error" role="alert">{t("settings.iam.loadFailed", { error })}</div> : null}
      {!loading && !error && overview ? renderTab({
        tab,
        overview,
        requests,
        roster,
        username,
        canManage,
        assignRole: async (identity, role) => {
          await submitIamAccessRequest(auth, client.readApiBaseUrl, {
            idempotencyKey: crypto.randomUUID(),
            identityProvider: identity.provider,
            targetSubjectId: identity.subjectId,
            targetUsername: identity.username ?? identity.displayName,
            operation: "set",
            role,
            justification: `Owner requested ${role} role for ${identity.displayName}.`,
          });
          await load();
        },
        auth,
        client,
        reload: load,
      }) : null}
    </div>
  );
}

function renderTab(props: {
  readonly tab: IamTab;
  readonly overview: IamOverview;
  readonly requests: readonly IamAccessRequest[];
  readonly roster: readonly IdentityRosterItem[];
  readonly username: string;
  readonly canManage: boolean;
  readonly assignRole: (
    identity: IdentityRosterItem | HumanIdentityResult,
    role: Exclude<IamRole, "BreakGlass">,
  ) => Promise<void>;
  readonly auth: AuthContext;
  readonly client: ReadApiClient;
  readonly reload: () => Promise<void>;
}) {
  switch (props.tab) {
    case "my-access":
      return <MyAccess overview={props.overview} username={props.username} auth={props.auth} />;
    case "users":
      return (
        <UsersView
          overview={props.overview}
          username={props.username}
          requests={props.requests}
          roster={props.roster}
          client={props.client}
          canManage={props.canManage}
          onAssign={props.assignRole}
        />
      );
    case "roles":
      return <RolesView roles={props.overview.roles} />;
    case "requests":
      return (
        <AccessRequestsView
          requests={props.requests}
          roster={props.roster}
          canManage={props.canManage}
          auth={props.auth}
          client={props.client}
          reload={props.reload}
        />
      );
  }
}

function MyAccess({ overview, username, auth }: {
  readonly overview: IamOverview;
  readonly username: string;
  readonly auth: AuthContext;
}) {
  const identity = iamIdentityPresentation(auth, overview);
  return (
    <section class="settings-iam-panel" aria-labelledby="settings-iam-my-access">
      <header class="settings-iam-panel-head">
        <div>
          <h3 id="settings-iam-my-access">{t("settings.iam.currentAccess")}</h3>
          <p>{t("settings.iam.currentAccessHint")}</p>
        </div>
        <div class="settings-role-list" aria-label={t("settings.iam.currentRoles")}>
          {overview.principal.roles.length > 0
            ? overview.principal.roles.map((role) => (
                <StatusPill key={role} kind={roleKind(role)} label={role} />
              ))
            : <StatusPill kind="danger" label={t("settings.iam.unassigned")} />}
        </div>
      </header>

      <div class="settings-access-strip" aria-label={t("settings.iam.accessSummary")}>
        <div>
          <span>{t("settings.iam.identityProvider")}</span>
          <strong>{t(`settings.iam.identitySource.${identity.source}`)}</strong>
        </div>
        <div>
          <span>{t("settings.iam.role")}</span>
          <strong>{overview.principal.roles.join(", ") || t("settings.iam.unassigned")}</strong>
        </div>
        <div>
          <span>{t("settings.iam.capabilities")}</span>
          <strong>{overview.principal.capabilities.length}</strong>
        </div>
      </div>

      <div class="settings-access-body">
        <dl class="settings-access-details">
          <dt>{t("settings.iam.signedInAs")}</dt>
          <dd>{username}</dd>
          {identity.subjectId ? (
            <>
              <dt>{t("settings.iam.subjectId")}</dt>
              <dd><code>{identity.subjectId}</code></dd>
            </>
          ) : null}
          <dt>{t("settings.iam.authorizationMode")}</dt>
          <dd>
            <strong>{t(`settings.iam.authorizationValue.${identity.authorization}`)}</strong>
            {identity.authorization === "local-ceiling" ? (
              <small>{t("settings.iam.localCeilingHint")}</small>
            ) : null}
          </dd>
        </dl>
        <div class="settings-capability-panel">
          <span>{t("settings.iam.effectiveCapabilities")}</span>
          <div class="settings-capability-chips">
            {overview.principal.capabilities.map((capability) => (
              <span key={capability} title={capability}>{humanizeCapability(capability)}</span>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

export interface IamIdentityPresentation {
  readonly source: "local-entra" | "azure-cli" | "entra" | "development";
  readonly subjectId: string | null;
  readonly authorization: "local-ceiling" | "provider-roles";
}

export function iamIdentityPresentation(
  auth: AuthContext,
  overview: IamOverview,
): IamIdentityPresentation {
  if (auth.localAzureCli && auth.account) {
    return {
      source: "azure-cli",
      subjectId: auth.account.localAccountId,
      authorization: "local-ceiling",
    };
  }
  if (auth.devMode && auth.account) {
    return {
      source: "local-entra",
      subjectId: auth.account.localAccountId,
      authorization: "local-ceiling",
    };
  }
  if (auth.account) {
    return {
      source: "entra",
      subjectId: auth.account.localAccountId,
      authorization: "provider-roles",
    };
  }
  return {
    source: "development",
    subjectId: null,
    authorization: "local-ceiling",
  };
}

function humanizeCapability(capability: string): string {
  const acronyms: Readonly<Record<string, string>> = { pr: "PR", hil: "HIL", iam: "IAM" };
  return capability.split("-").map((word, index) => (
    acronyms[word] ?? (index === 0 ? word.charAt(0).toUpperCase() + word.slice(1) : word)
  )).join(" ");
}

function UsersView({
  overview,
  username,
  requests,
  roster,
  client,
  canManage,
  onAssign,
}: {
  readonly overview: IamOverview;
  readonly username: string;
  readonly requests: readonly IamAccessRequest[];
  readonly roster: readonly IdentityRosterItem[];
  readonly client: ReadApiClient;
  readonly canManage: boolean;
  readonly onAssign: (
    identity: IdentityRosterItem | HumanIdentityResult,
    role: Exclude<IamRole, "BreakGlass">,
  ) => Promise<void>;
}) {
  const users = referencedUsers(overview, username, requests);
  return (
    <DirectoryUserSearch
      client={client}
      canManage={canManage}
      roster={roster}
      referencedUsers={users}
      onAssign={onAssign}
    />
  );
}

function RolesView({ roles }: { readonly roles: readonly IamRoleDefinition[] }) {
  return (
    <section class="settings-iam-panel" aria-labelledby="settings-iam-roles">
      <header class="settings-iam-panel-head">
        <div>
          <h3 id="settings-iam-roles">{t("settings.iam.roles")}</h3>
          <p>{t("settings.iam.rolesHint")}</p>
        </div>
        <StatusPill kind="neutral" label={t("settings.iam.roleCount", { count: roles.length })} />
      </header>
      <DataTable
        columns={[
          {
            key: "role",
            header: t("settings.iam.role"),
            render: (role: IamRoleDefinition) => (
              <StatusPill kind={roleKind(role.value)} label={role.value} />
            ),
          },
          {
            key: "capabilities",
            header: t("settings.iam.capabilities"),
            render: (role: IamRoleDefinition) => (
              <span class="settings-capability-chips">
                {role.capabilities.map((capability) => (
                  <span key={capability} title={capability}>
                    {humanizeCapability(capability)}
                  </span>
                ))}
              </span>
            ),
          },
          {
            key: "assignment",
            header: t("settings.iam.assignment"),
            render: (role: IamRoleDefinition) => role.routineAssignment
              ? t("settings.iam.routine")
              : t("settings.iam.emergencyOnly"),
          },
        ]}
        rows={roles}
        keyOf={(role) => role.value}
        caption={t("settings.iam.roleTableCaption")}
      />
      <p class="settings-iam-panel-foot">{t("settings.iam.assignmentBoundaryHint")}</p>
    </section>
  );
}

function referencedUsers(
  overview: IamOverview,
  username: string,
  requests: readonly IamAccessRequest[],
): readonly IdentityRosterItem[] {
  const users = new Map<string, IdentityRosterItem>();
  users.set(`current:${overview.principal.oid}`, {
    provider: "authenticated",
    subjectId: overview.principal.oid,
    displayName: username,
    principalType: "person",
    username,
    roles: overview.principal.roles,
    active: true,
  });
  for (const request of requests) {
    const key = `${request.identityProvider}:${request.targetSubjectId}`;
    if (!users.has(key)) {
      users.set(key, {
        provider: request.identityProvider,
        subjectId: request.targetSubjectId,
        displayName: request.targetUsername,
        principalType: "person",
        username: request.targetUsername,
        roles: [request.role],
        active: request.status !== "rejected",
      });
    }
  }
  return [...users.values()];
}

function currentTokenRoles(auth: AuthContext): readonly IamRole[] {
  const claims = (auth.account?.idTokenClaims ?? {}) as Record<string, unknown>;
  const rawRoles = claims["roles"];
  if (!Array.isArray(rawRoles)) return [];
  return rawRoles.filter((role): role is IamRole =>
    typeof role === "string"
    && ["Reader", "Contributor", "Approver", "Owner", "BreakGlass"].includes(role)
  );
}

function roleKind(role: IamRole): PillKind {
  switch (role) {
    case "Reader": return "neutral";
    case "Contributor": return "info";
    case "Approver": return "success";
    case "Owner": return "warning";
    case "BreakGlass": return "danger";
  }
}
