import { describe, expect, it } from "vitest";
import { parseTurns, serializeTurns } from "./transcript-store";

const SHA = "b".repeat(64);

describe("grounded code transcript", () => {
  it("round-trips terminal code artifacts", () => {
    const serialized = serializeTurns([
      {
        id: "code-1",
        role: "deck",
        text: "Generated code",
        at: "10:00:00",
        terminal: true,
        codeArtifacts: [
          {
            artifact_ref: `code:sha256:${SHA}`,
            language: "python",
            content: "print('ok')\n",
            sha256: SHA,
            validation_status: "valid",
            validation_detail: null,
          },
        ],
      },
    ]);

    const parsed = parseTurns(serialized);

    expect(parsed[0]?.codeArtifacts?.[0]?.content).toBe("print('ok')\n");
  });

  it("drops malformed persisted code artifacts", () => {
    const parsed = parseTurns(JSON.stringify([
      {
        id: "code-1",
        role: "deck",
        text: "Generated code",
        at: "10:00:00",
        codeArtifacts: [{ artifact_ref: "../../runtime", content: "bad" }],
      },
    ]));

    expect(parsed[0]?.codeArtifacts).toBeUndefined();
  });
});
