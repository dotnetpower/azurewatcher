import { t } from "../i18n";
import type { InvestigationActivity } from "./backend";

export function upsertInvestigationActivity(
  activities: readonly InvestigationActivity[],
  incoming: InvestigationActivity,
): readonly InvestigationActivity[] {
  const index = activities.findIndex((item) => item.activityId === incoming.activityId);
  if (index < 0) return [...activities, incoming];
  return activities.map((item, itemIndex) => itemIndex === index ? incoming : item);
}

function statusMark(status: InvestigationActivity["status"]): string {
  if (status === "completed") return "\u2713";
  if (status === "unavailable") return "!";
  if (status === "failed") return "\u00d7";
  return "";
}

function statusLabel(status: InvestigationActivity["status"]): string {
  return t(`deck.investigation.${status}`);
}

export function InvestigationTimeline({
  activities,
  running,
}: {
  readonly activities: readonly InvestigationActivity[];
  readonly running: boolean;
}) {
  return (
    <section class="deck-investigation" aria-label={t("deck.investigation.label")}>
      <header class="deck-investigation-head">
        <strong>{t("deck.investigation.title")}</strong>
        <span class="muted">
          {running ? t("deck.investigation.running") : t("deck.investigation.finished")}
        </span>
      </header>
      <ol class="deck-investigation-list">
        {activities.map((activity) => {
          const progress = activity.completed !== null && activity.total !== null
            ? `${activity.completed}/${activity.total}`
            : null;
          return (
            <li
              key={activity.activityId}
              class={`deck-investigation-item is-${activity.status}`}
            >
              <span class="deck-investigation-state" aria-hidden="true">
                {statusMark(activity.status)}
              </span>
              <span class="deck-investigation-copy">
                <strong>{activity.label}</strong>
                {activity.detail ? <small>{activity.detail}</small> : null}
              </span>
              <span class="deck-investigation-meta muted">
                {progress ?? statusLabel(activity.status)}
              </span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
