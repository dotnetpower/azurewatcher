import { observationSourceLabel } from "../hooks/observation-source";
import { t } from "../i18n";
import { formatConsoleTimestamp } from "../time-format";
import { routeHref } from "../router";
import {
  isLiveWorkActivity,
  type LiveAgentActivityEvent,
} from "./agents.model";

const DISPLAY_LIMIT = 20;

interface Props {
  readonly events: readonly LiveAgentActivityEvent[];
  readonly selectedAgent: string | null;
}

export function LiveActivityJournal({ events, selectedAgent }: Props) {
  const visible = events.slice(0, DISPLAY_LIMIT);
  const workCount = events.filter(isLiveWorkActivity).length;
  const subject = selectedAgent ?? t("agentActivity.live.pantheon");

  return (
    <section class="aa-live-journal" aria-labelledby="aa-live-journal-title">
      <header>
        <div>
          <span>{t("agentActivity.live.session")}</span>
          <h3 id="aa-live-journal-title">{t("agentActivity.live.title")}</h3>
        </div>
        <span>{t("agentActivity.live.counts", { frames: events.length, events: workCount })}</span>
      </header>

      {workCount === 0 ? (
        <p class="aa-live-waiting">
          <strong>{t("agentActivity.live.noWork")}</strong>
          <span>{t("agentActivity.live.waiting", { subject })}</span>
        </p>
      ) : null}

      {visible.length === 0 ? (
        <p class="aa-live-empty">{t("agentActivity.live.noFrames")}</p>
      ) : (
        <ol class="aa-live-events">
          {visible.map((event, index) => (
            <li key={`${event.kind}:${event.ts}:${event.agent}:${event.correlationId ?? "none"}:${index}`}>
              <time dateTime={event.ts}>{formatConsoleTimestamp(event.ts)}</time>
              <span class={`aa-live-kind ${isLiveWorkActivity(event) ? "is-work" : ""}`}>
                {eventKindLabel(event)}
              </span>
              <div>
                <strong>{event.agents.join(" -> ") || event.agent}</strong>
                <span>{event.summary}</span>
                {event.detail && event.detail !== event.summary ? <small>{event.detail}</small> : null}
              </div>
              <div class="aa-live-evidence">
                <span>{observationSourceLabel(event.source)}</span>
                {event.correlationId ? (
                  <a href={routeHref("trace", { params: { correlation: event.correlationId } })}>
                    {event.correlationId}
                  </a>
                ) : <span>{t("agentActivity.live.noCorrelation")}</span>}
              </div>
            </li>
          ))}
        </ol>
      )}
      {events.length > DISPLAY_LIMIT ? (
        <p class="aa-live-retention">{t("agentActivity.live.retention", { count: DISPLAY_LIMIT, total: events.length })}</p>
      ) : null}
    </section>
  );
}

function eventKindLabel(event: LiveAgentActivityEvent): string {
  if (event.kind === "incident.ticket") return t("agentActivity.live.incident");
  if (event.kind === "conversation.turn") return t("agentActivity.live.handoff");
  return event.state ? t(`agents.state.${event.state}`) : t("agentActivity.live.state");
}
