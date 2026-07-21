/** Return how many already-paced deltas the UI may paint in one frame. */
export function streamPaintBatchSize(backlog: number): number {
  if (backlog > 24) return 3;
  if (backlog > 8) return 2;
  return 1;
}

/** Drain one visual frame while preserving byte-for-byte answer order. */
export function drainStreamPaint(queue: string[]): string {
  return queue.splice(0, streamPaintBatchSize(queue.length)).join("");
}

/** Return whether terminal completion must not wait for display frames. */
export function shouldFlushStreamPaintSynchronously(
  visibilityState: string,
  focused: boolean,
): boolean {
  return visibilityState === "hidden" || !focused;
}

/** Drain every paced delta when no visible frame can be relied on. */
export function flushStreamPaint(queue: string[]): string {
  return queue.splice(0).join("");
}
