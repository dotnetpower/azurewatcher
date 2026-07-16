import { currentRoute, panelPath } from "../router";

const AGENT_WORKSPACE_ITEMS = [
  { id: "agents", label: "Roster" },
  { id: "pantheon", label: "Organization" },
  { id: "agent-activity", label: "Activity" },
  { id: "handover", label: "Handover" },
] as const;

export function AgentWorkspaceNav() {
  const activeId = currentRoute().panelId;
  return (
    <nav class="agent-workspace-nav" aria-label="Agent workspace">
      {AGENT_WORKSPACE_ITEMS.map((item) => (
        <a
          key={item.id}
          href={panelPath(item.id)}
          class={activeId === item.id ? "is-active" : undefined}
          aria-current={activeId === item.id ? "page" : undefined}
        >
          {item.label}
        </a>
      ))}
    </nav>
  );
}
