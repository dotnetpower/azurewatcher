export interface UnauthorizedResponse {
  readonly status: 401;
  readonly message: string;
}

export function observeUnauthorizedApiResponses(
  baseUrls: readonly string[],
  onUnauthorized: (error: UnauthorizedResponse) => void,
): () => void {
  const originalFetch = globalThis.fetch;
  const apiBases = baseUrls
    .filter((value) => value.trim().length > 0)
    .map((value) => new URL(value, globalThis.location?.href));
  const observedFetch: typeof fetch = async (input, init) => {
    const response = await originalFetch(input, init);
    if (response.status === 401 && isApiRequest(input, apiBases)) {
      onUnauthorized({
        status: 401,
        message: "Authentication is required. Sign in again to continue.",
      });
    }
    return response;
  };
  globalThis.fetch = observedFetch;
  return () => {
    if (globalThis.fetch === observedFetch) globalThis.fetch = originalFetch;
  };
}

function isApiRequest(
  input: RequestInfo | URL,
  apiBases: readonly URL[],
): boolean {
  const requestUrl = new URL(
    typeof input === "string"
      ? input
      : input instanceof URL
        ? input.href
        : input.url,
    globalThis.location?.href,
  );
  return apiBases.some((base) => {
    const basePath = base.pathname.replace(/\/$/, "");
    return requestUrl.origin === base.origin
      && (requestUrl.pathname === basePath || requestUrl.pathname.startsWith(`${basePath}/`));
  });
}