import { currentRoute, routeHref } from "../router";
import { t } from "../i18n";

const AGENT_WORKSPACE_ITEMS = [
  {
    id: "fleet",
    labelKey: "agents.workspace.fleet",
    href: () => routeHref("agents"),
    active: () => currentRoute().panelId === "agents" && currentRoute().search.get("view") !== "org",
  },
  {
    id: "org",
    labelKey: "agents.workspace.org",
    href: () => routeHref("pantheon"),
    active: () => currentRoute().panelId === "pantheon" || (
      currentRoute().panelId === "agents" && currentRoute().search.get("view") === "org"
    ),
  },
  {
    id: "activity",
    labelKey: "agents.workspace.activity",
    href: () => routeHref("agent-activity"),
    active: () => currentRoute().panelId === "agent-activity",
  },
] as const;

export function AgentWorkspaceNav() {
  return (
    <nav class="agent-workspace-nav" aria-label={t("agents.workspace.label")}>
      {AGENT_WORKSPACE_ITEMS.map((item) => {
        const active = item.active();
        return (
          <a
            key={item.id}
            href={item.href()}
            class={active ? "is-active" : undefined}
            aria-current={active ? "page" : undefined}
          >
            {t(item.labelKey)}
          </a>
        );
      })}
    </nav>
  );
}
