import type { AuthContext } from "../auth";

let chatAuth: AuthContext | null = null;

export function setChatAuth(auth: AuthContext | null): void {
  chatAuth = auth;
}

export async function chatRequestHeaders(
  contentType: boolean = false,
): Promise<Record<string, string>> {
  const headers: Record<string, string> = {};
  if (contentType) headers["content-type"] = "application/json";
  const authorization = await chatAuth?.getAuthorizationHeader() ?? null;
  if (authorization) headers.authorization = authorization;
  return headers;
}
