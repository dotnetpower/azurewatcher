/**
 * One-shot briefing renderer.
 *
 * Renders the briefing block IR to the terminal with Ink (colour, cards, bars),
 * then exits so stdin is handed back to the terminal. The interactive prompt is
 * NOT an Ink component - it is a Node `readline` REPL (see `../../repl.ts`) so
 * IME composition (Korean etc.), native cursor movement, and history work like
 * any normal shell. Ink's full-screen repaint fights the terminal's input
 * cursor, which is why input lives outside Ink.
 */

import { Box, render, Static, useApp } from "ink";
import { useEffect } from "react";

import type { Block } from "../../view-model/blocks.js";
import { BlockView } from "./Briefing.js";

export function renderBriefing(blocks: readonly Block[]): Promise<void> {
  const visible = blocks.filter((b) => b.type !== "prompt");
  function Briefing() {
    const { exit } = useApp();
    useEffect(() => {
      exit();
    }, [exit]);
    // <Static> commits the briefing to the scrollback permanently, so it
    // survives Ink's exit (a dynamic region would be erased on unmount).
    return (
      <Static items={visible}>
        {(block, i) => (
          <Box key={i}>
            <BlockView block={block} />
          </Box>
        )}
      </Static>
    );
  }
  const { waitUntilExit } = render(<Briefing />);
  return waitUntilExit().then(() => undefined);
}
