import type { AuthContext } from "../auth";
import {
  decodeIamAccessRequest,
  type IamAccessRequest,
  type IamAccessRequestInput,
} from "./settings-iam.model";

export async function submitIamAccessRequest(
  auth: AuthContext,
  readApiBaseUrl: string,
  input: IamAccessRequestInput,
): Promise<IamAccessRequest> {
  const headers: Record<string, string> = {
    accept: "application/json",
    "content-type": "application/json",
  };
  const authorization = await auth.getAuthorizationHeader();
  if (authorization !== null) headers["authorization"] = authorization;
  const response = await fetch(new URL("/iam/access-requests", readApiBaseUrl), {
    method: "POST",
    headers,
    credentials: "omit",
    body: JSON.stringify({
      idempotency_key: input.idempotencyKey,
      identity_provider: input.identityProvider,
      target_subject_id: input.targetSubjectId,
      target_username: input.targetUsername,
      operation: input.operation,
      role: input.role,
      justification: input.justification,
    }),
  });
  if (!response.ok) {
    throw new Error(await errorMessage(response));
  }
  return decodeIamAccessRequest(await response.json());
}

export async function submitSelfAccessRequest(
  auth: AuthContext,
  readApiBaseUrl: string,
  input: { readonly idempotencyKey: string; readonly message?: string },
): Promise<IamAccessRequest> {
  const headers: Record<string, string> = {
    accept: "application/json",
    "content-type": "application/json",
  };
  const authorization = await auth.getAuthorizationHeader();
  if (authorization !== null) headers["authorization"] = authorization;
  const response = await fetch(new URL("/iam/access-requests/self", readApiBaseUrl), {
    method: "POST",
    headers,
    credentials: "omit",
    body: JSON.stringify({
      idempotency_key: input.idempotencyKey,
      ...(input.message?.trim() ? { message: input.message.trim() } : {}),
    }),
  });
  if (!response.ok) throw new Error(await errorMessage(response));
  return decodeIamAccessRequest(await response.json());
}

export async function reviewIamAccessRequest(
  auth: AuthContext,
  readApiBaseUrl: string,
  requestId: string,
  input: { readonly decision: "approve" | "reject"; readonly justification: string },
): Promise<IamAccessRequest> {
  const headers: Record<string, string> = {
    accept: "application/json",
    "content-type": "application/json",
  };
  const authorization = await auth.getAuthorizationHeader();
  if (authorization !== null) headers["authorization"] = authorization;
  const path = `/iam/access-requests/${encodeURIComponent(requestId)}/decision`;
  const response = await fetch(new URL(path, readApiBaseUrl), {
    method: "POST",
    headers,
    credentials: "omit",
    body: JSON.stringify(input),
  });
  if (!response.ok) throw new Error(await errorMessage(response));
  return decodeIamAccessRequest(await response.json());
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const body = await response.json() as { error?: { message?: unknown } };
    if (typeof body.error?.message === "string") return body.error.message;
  } catch {
    // Fall through to the stable status message.
  }
  return `IAM access request failed (HTTP ${response.status})`;
}
