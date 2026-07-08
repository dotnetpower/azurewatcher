/**
 * SVG glyphs for the LeftRail group icons.
 *
 * Single responsibility: given a group id, return a JSX SVG. No layout,
 * no interaction, no state. Icons intentionally use ``currentColor`` so
 * the rail styling controls their tint.
 *
 * Icon choices reflect operator intent:
 *  - Now       : lightning bolt (real-time)
 *  - History   : clock rewind (past)
 *  - Knowledge : nodes / graph (what the system knows)
 *  - Safety    : shield check (protection)
 *  - Overview  : bar chart (summary)
 */

import type { JSX } from "preact";
import type { PanelGroup } from "../panels";

const iconProps = {
  width: 20,
  height: 20,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  "stroke-width": 1.8,
  "stroke-linecap": "round" as const,
  "stroke-linejoin": "round" as const,
};

function IconNow(): JSX.Element {
  return (
    <svg {...iconProps}>
      <path d="M13 2 L3 14 L11 14 L11 22 L21 10 L13 10 Z" />
    </svg>
  );
}

function IconHistory(): JSX.Element {
  return (
    <svg {...iconProps}>
      <path d="M12 4 A8 8 0 1 1 4.6 15.5" />
      <path d="M4 4 L4 9 L9 9" />
      <path d="M12 8 L12 12 L15 14" />
    </svg>
  );
}

function IconKnowledge(): JSX.Element {
  return (
    <svg {...iconProps}>
      <circle cx="6" cy="6" r="2.2" />
      <circle cx="18" cy="6" r="2.2" />
      <circle cx="12" cy="18" r="2.2" />
      <path d="M6.5 8 L11.2 16.2" />
      <path d="M17.5 8 L12.8 16.2" />
      <path d="M8 6 L16 6" />
    </svg>
  );
}

function IconSafety(): JSX.Element {
  return (
    <svg {...iconProps}>
      <path d="M12 3 L4 6 V12 C4 17 8 20.5 12 21.5 C16 20.5 20 17 20 12 V6 Z" />
      <path d="M9 12 L11 14 L15 10" />
    </svg>
  );
}

function IconOverview(): JSX.Element {
  return (
    <svg {...iconProps}>
      <path d="M4 21 L4 3" />
      <path d="M4 21 L21 21" />
      <rect x="7" y="12" width="3" height="7" />
      <rect x="12" y="8" width="3" height="11" />
      <rect x="17" y="14" width="3" height="5" />
    </svg>
  );
}

export function groupIcon(group: PanelGroup): JSX.Element {
  switch (group) {
    case "now":
      return <IconNow />;
    case "history":
      return <IconHistory />;
    case "knowledge":
      return <IconKnowledge />;
    case "safety":
      return <IconSafety />;
    case "overview":
      return <IconOverview />;
  }
}
