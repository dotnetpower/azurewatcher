import type { AuthContext } from "../auth";
import { putGovernedJson } from "../governed-command";
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
  return decodeIamAccessRequest(await putGovernedJson(
    auth,
    readApiBaseUrl,
    "/iam/access-requests",
    {
      idempotency_key: input.idempotencyKey,
      identity_provider: input.identityProvider,
      target_subject_id: input.targetSubjectId,
      target_username: input.targetUsername,
      operation: input.operation,
      role: input.role,
      justification: input.justification,
    },
    "POST",
  ));
}

export async function submitSelfAccessRequest(
  auth: AuthContext,
  readApiBaseUrl: string,
  input: { readonly idempotencyKey: string; readonly message?: string },
): Promise<IamAccessRequest> {
  return decodeIamAccessRequest(await putGovernedJson(
    auth,
    readApiBaseUrl,
    "/iam/access-requests/self",
    {
      idempotency_key: input.idempotencyKey,
      ...(input.message?.trim() ? { message: input.message.trim() } : {}),
    },
    "POST",
  ));
}

export async function reviewIamAccessRequest(
  auth: AuthContext,
  readApiBaseUrl: string,
  requestId: string,
  input: { readonly decision: "approve" | "reject"; readonly justification: string },
): Promise<IamAccessRequest> {
  const path = `/iam/access-requests/${encodeURIComponent(requestId)}/decision`;
  return decodeIamAccessRequest(await putGovernedJson(
    auth,
    readApiBaseUrl,
    path,
    { ...input },
    "POST",
  ));
}
