const LOCAL_AUTH_BYPASS_KEY = "fdai:console:local-auth-bypass:v1";

type StorageReader = Pick<Storage, "getItem">;
type StorageWriter = Pick<Storage, "setItem" | "removeItem">;

export function readLocalAuthBypass(
  storage: StorageReader | null = browserStorage(),
): boolean {
  if (storage === null) return false;
  try {
    return storage.getItem(LOCAL_AUTH_BYPASS_KEY) === "1";
  } catch {
    return false;
  }
}

export function enableLocalAuthBypass(
  storage: StorageWriter | null = browserWritableStorage(),
): boolean {
  if (storage === null) return false;
  try {
    storage.setItem(LOCAL_AUTH_BYPASS_KEY, "1");
    return true;
  } catch {
    return false;
  }
}

export function clearLocalAuthBypass(
  storage: StorageWriter | null = browserWritableStorage(),
): boolean {
  if (storage === null) return false;
  try {
    storage.removeItem(LOCAL_AUTH_BYPASS_KEY);
    return true;
  } catch {
    return false;
  }
}

export async function establishLocalAuthBypass(
  probeAnonymousAccess: () => Promise<unknown>,
  storage: StorageWriter | null = browserWritableStorage(),
): Promise<void> {
  await probeAnonymousAccess();
  if (!enableLocalAuthBypass(storage)) {
    throw new Error("Browser session storage is unavailable.");
  }
}

function browserStorage(): StorageReader | null {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

function browserWritableStorage(): StorageWriter | null {
  return browserStorage() as StorageWriter | null;
}
