import { afterEach, describe, expect, test, vi } from "vitest";

import { readSseChunk } from "./sse-reader";

afterEach(() => {
  vi.useRealTimers();
});

describe("SSE inactivity guard", () => {
  test("cancels a reader that emits no bytes before the timeout", async () => {
    vi.useFakeTimers();
    const cancel = vi.fn();
    const stream = new ReadableStream<Uint8Array>({ cancel });
    const reader = stream.getReader();
    const result = readSseChunk(reader, 1_000);
    const rejection = expect(result).rejects.toThrow(/inactivity timeout/);

    await vi.advanceTimersByTimeAsync(1_000);

    await rejection;
    expect(cancel).toHaveBeenCalledOnce();
  });

  test("returns a chunk before the timeout", async () => {
    vi.useFakeTimers();
    const chunk = new Uint8Array([1, 2, 3]);
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(chunk);
      },
    });

    await expect(readSseChunk(stream.getReader(), 1_000)).resolves.toEqual({
      value: chunk,
      done: false,
    });
  });
});