import { describe, expect, it } from "vitest";
import { drainStreamPaint, streamPaintBatchSize } from "./stream-paint";

describe("stream paint batching", () => {
  it("uses a bounded adaptive batch per display frame", () => {
    expect(streamPaintBatchSize(1)).toBe(1);
    expect(streamPaintBatchSize(9)).toBe(2);
    expect(streamPaintBatchSize(25)).toBe(3);
    expect(streamPaintBatchSize(1_000)).toBe(3);
  });

  it("never dumps a large preparing backlog in one paint", () => {
    const queue = Array.from({ length: 60 }, (_, index) => `${index},`);
    const first = drainStreamPaint(queue);
    expect(first).toBe("0,1,2,");
    expect(queue).toHaveLength(57);
  });

  it("reconstructs every delta in order", () => {
    const source = Array.from({ length: 60 }, (_, index) => `[${index}]`);
    const queue = [...source];
    const frames: string[] = [];
    while (queue.length > 0) frames.push(drainStreamPaint(queue));
    expect(frames.join("")).toBe(source.join(""));
    expect(frames.length).toBeGreaterThan(20);
  });
});
