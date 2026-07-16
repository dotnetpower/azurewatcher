import type { AuthContext } from "./auth";
import { loadConfig } from "./config";

export interface UserPreferencePayload {
  readonly principal_id: string;
  readonly locale: "en" | "ko";
  readonly verbosity: "concise" | "detailed";
  readonly timezone: string | null;
  readonly share_with_learner: boolean;
  readonly revision: number;
}

export interface BriefingRunPayload {
  readonly run_id: string;
  readonly title: string;
  readonly body_markdown: string;
  readonly status: string;
  readonly item_count: number;
  readonly evidence_refs: readonly string[];
  readonly source_errors: readonly string[];
}

export interface BriefingSubscriptionPayload {
  readonly subscription_id: string;
  readonly name: string;
  readonly cron_expression: string;
  readonly timezone: string;
  readonly enabled: boolean;
  readonly next_run_at: string;
  readonly spec: Readonly<Record<string, unknown>>;
}

export interface ConversationPolicyPayload {
  readonly policy_id: string;
  readonly kind: "opening_briefing" | "response_defaults";
  readonly enabled: boolean;
  readonly revision: number;
  readonly source_turn_id: string;
  readonly briefing_spec: Readonly<Record<string, unknown>> | null;
  readonly response_defaults: Readonly<Record<string, string>>;
}

export interface UserMemoryPayload {
  readonly memory_id: string;
  readonly category: "preference" | "context" | "goal";
  readonly body: string;
  readonly source_turn_id: string;
  readonly created_at: string;
  readonly expires_at: string | null;
}

export interface ConversationSummaryPayload {
  readonly conversation_id: string;
  readonly channel_id: string;
  readonly started_at: string;
  readonly last_active: string;
  readonly status: string;
  readonly latest_operator_turn_id: string | null;
}

export interface ConversationTurnPayload {
  readonly turn_id: string;
  readonly conversation_id: string;
  readonly turn_index: number;
  readonly role: "operator" | "assistant" | "tool" | "system";
  readonly content: string;
  readonly recorded_at: string;
  readonly metadata: Readonly<Record<string, string>>;
}

export interface UserContextPayload {
  readonly preference: UserPreferencePayload | null;
  readonly memories: readonly UserMemoryPayload[];
  readonly policies: readonly ConversationPolicyPayload[];
  readonly subscriptions: readonly BriefingSubscriptionPayload[];
  readonly briefing_runs: readonly BriefingRunPayload[];
  readonly conversations: readonly ConversationSummaryPayload[];
}

let authContext: AuthContext | null = null;

export function setUserContextAuth(auth: AuthContext | null): void {
  authContext = auth;
}

export async function fetchOpeningBriefing(conversationId: string): Promise<BriefingRunPayload | null> {
  const response = await request("/me/opening-briefing", "POST", {
    conversation_id: conversationId,
  });
  return (response.briefing as BriefingRunPayload | null | undefined) ?? null;
}

export async function fetchConversationTurns(
  conversationId: string,
): Promise<readonly ConversationTurnPayload[]> {
  const response = await request(
    `/me/conversations/${encodeURIComponent(conversationId)}/turns?limit=1000`,
    "GET",
  );
  return (response.turns as readonly ConversationTurnPayload[] | undefined) ?? [];
}

export async function putUserPreference(input: {
  readonly locale: "en" | "ko";
  readonly verbosity: "concise" | "detailed";
  readonly timezone: string | null;
  readonly share_with_learner: boolean;
  readonly expected_revision?: number;
}): Promise<UserPreferencePayload> {
  return await request("/me/preferences", "PUT", input) as unknown as UserPreferencePayload;
}

export async function putConversationPolicy(input: Record<string, unknown>): Promise<Record<string, unknown>> {
  return request("/me/policies", "PUT", { ...input, confirmed: true });
}

export async function deleteConversationPolicy(policyId: string): Promise<void> {
  await request(`/me/policies/${encodeURIComponent(policyId)}`, "DELETE");
}

export async function deleteUserMemory(memoryId: string): Promise<void> {
  await request(`/me/memories/${encodeURIComponent(memoryId)}`, "DELETE");
}

export async function createBriefingSubscription(input: Record<string, unknown>): Promise<Record<string, unknown>> {
  return request("/me/briefing-subscriptions", "POST", { ...input, confirmed: true });
}

export async function deleteBriefingSubscription(subscriptionId: string): Promise<void> {
  await request(`/me/briefing-subscriptions/${encodeURIComponent(subscriptionId)}`, "DELETE");
}

async function request(
  path: string,
  method: "GET" | "POST" | "PUT" | "DELETE",
  body?: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const base = loadConfig().readApiBaseUrl || window.location.origin;
  const headers: Record<string, string> = { accept: "application/json" };
  if (body !== undefined) headers["content-type"] = "application/json";
  const authorization = authContext ? await authContext.getAuthorizationHeader() : null;
  if (authorization !== null) headers.authorization = authorization;
  const response = await fetch(`${base.replace(/\/$/, "")}${path}`, {
    method,
    headers,
    credentials: "omit",
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  });
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const payload = await response.json() as { detail?: string };
      detail = payload.detail ?? detail;
    } catch {
      /* keep status */
    }
    throw new Error(detail);
  }
  if (response.status === 204) return {};
  return await response.json() as Record<string, unknown>;
}
