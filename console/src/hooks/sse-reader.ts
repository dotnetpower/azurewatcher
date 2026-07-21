export const SSE_INACTIVITY_TIMEOUT_MS = 45_000;

export async function readSseChunk(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  timeoutMs = SSE_INACTIVITY_TIMEOUT_MS,
): Promise<ReadableStreamReadResult<Uint8Array>> {
  let timer: ReturnType<typeof globalThis.setTimeout> | undefined;
  const timeout = new Promise<never>((_resolve, reject) => {
    timer = globalThis.setTimeout(
      () => reject(new Error("SSE stream exceeded the inactivity timeout")),
      timeoutMs,
    );
  });
  try {
    return await Promise.race([reader.read(), timeout]);
  } catch (error) {
    await reader.cancel(error).catch(() => undefined);
    throw error;
  } finally {
    if (timer !== undefined) globalThis.clearTimeout(timer);
  }
}