import { currentRoute, panelPath } from "../router";
import { t } from "../i18n";

const AGENT_WORKSPACE_ITEMS = [
  { id: "agents", labelKey: "agents.workspace.roster" },
  { id: "pantheon", labelKey: "agents.workspace.organization" },
  { id: "agent-activity", labelKey: "agents.workspace.activity" },
  { id: "handover", labelKey: "agents.workspace.handover" },
] as const;

export function AgentWorkspaceNav() {
  const activeId = currentRoute().panelId;
  return (
    <nav class="agent-workspace-nav" aria-label={t("agents.workspace.label")}>
      {AGENT_WORKSPACE_ITEMS.map((item) => (
        <a
          key={item.id}
          href={panelPath(item.id)}
          class={activeId === item.id ? "is-active" : undefined}
          aria-current={activeId === item.id ? "page" : undefined}
        >
          {t(item.labelKey)}
        </a>
      ))}
    </nav>
  );
}
