/**
 * Left rail navigation - 5 group icons, each with a hover popover
 * revealing the sub-panels in that group.
 *
 * Design (see the proposal thread + operator-console.md):
 * - Rail is a persistent 72px column pinned to the left. Only 5 icons
 *   ever appear here regardless of how many panels are wired. This
 *   caps the operator's initial cognitive load and scales gracefully
 *   as future panels land (Rules browser, Exemptions, Cost, etc.).
 * - Sub-panels appear in a floating popover ANCHORED to the rail on
 *   the right edge - the main content NEVER reflows on hover
 *   (Live cockpit's grid would jump otherwise).
 * - Interaction:
 *     * Mouse hover on a group icon (or on the popover itself) keeps
 *       the popover open. 180 ms close delay so a small mouse jitter
 *       between icon and popover does not close it.
 *     * Focus (keyboard) on an icon opens the popover.
 *     * ArrowUp / ArrowDown navigate between the 5 group icons.
 *     * Enter / Space on a focused icon "pins" the popover open (a
 *       second Enter closes it).
 *     * Escape closes any open popover and returns focus to the icon.
 *     * Clicking a sub-panel navigates and closes the popover.
 *
 * The rail is read-only nav; it never issues privileged calls, matching
 * the console contract in app-shape.instructions.md § Operator console.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "preact/hooks";
import { PANEL_GROUPS, panelsInGroup, type PanelGroup } from "../panels";
import { groupIcon } from "./rail-icons";

interface Props {
  readonly activePanelId: string;
}

interface ActiveGroupState {
  /** Which group's popover is currently visible, if any. */
  readonly group: PanelGroup | null;
  /** True when the popover is pinned open (keyboard toggle). */
  readonly pinned: boolean;
}

const CLOSE_DELAY_MS = 180;
/** Hover-intent delay before a group popover opens. A short dwell keeps the
 *  flyout from flashing open when the pointer merely crosses the rail on its
 *  way elsewhere (a frequent accidental trigger reported by operators).
 *  Keyboard focus still opens immediately - that is an explicit intent. */
const OPEN_DELAY_MS = 140;

export function LeftRail({ activePanelId }: Props) {
  const [state, setState] = useState<ActiveGroupState>({ group: null, pinned: false });
  const closeTimer = useRef<number | null>(null);
  const openTimer = useRef<number | null>(null);
  const iconRefs = useRef(new Map<PanelGroup, HTMLButtonElement | null>());
  const navRef = useRef<HTMLElement | null>(null);

  const activeGroup = useMemo<PanelGroup | null>(() => {
    for (const g of PANEL_GROUPS) {
      const panels = panelsInGroup(g.id);
      if (panels.some((p) => p.id === activePanelId)) return g.id;
    }
    return null;
  }, [activePanelId]);

  const cancelClose = useCallback(() => {
    if (closeTimer.current !== null) {
      window.clearTimeout(closeTimer.current);
      closeTimer.current = null;
    }
  }, []);

  const cancelOpen = useCallback(() => {
    if (openTimer.current !== null) {
      window.clearTimeout(openTimer.current);
      openTimer.current = null;
    }
  }, []);

  const scheduleClose = useCallback(() => {
    cancelClose();
    cancelOpen();
    closeTimer.current = window.setTimeout(() => {
      setState((prev) => (prev.pinned ? prev : { group: null, pinned: false }));
    }, CLOSE_DELAY_MS);
  }, [cancelClose, cancelOpen]);

  const openGroup = useCallback(
    (g: PanelGroup, { pin }: { pin: boolean } = { pin: false }) => {
      cancelClose();
      cancelOpen();
      setState((prev) => ({
        group: g,
        pinned: pin ? !(prev.group === g && prev.pinned) : prev.pinned,
      }));
    },
    [cancelClose, cancelOpen],
  );

  /** Open a group after the hover-intent dwell (pointer path only). */
  const scheduleOpen = useCallback(
    (g: PanelGroup) => {
      cancelClose();
      cancelOpen();
      openTimer.current = window.setTimeout(() => {
        openTimer.current = null;
        setState((prev) => ({ group: g, pinned: prev.pinned }));
      }, OPEN_DELAY_MS);
    },
    [cancelClose, cancelOpen],
  );

  const closeAll = useCallback(() => {
    cancelClose();
    cancelOpen();
    setState({ group: null, pinned: false });
  }, [cancelClose, cancelOpen]);

  // Escape / cleanup on unmount.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && state.group !== null) {
        closeAll();
        const focused = iconRefs.current.get(state.group);
        focused?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      cancelClose();
      cancelOpen();
    };
  }, [state.group, closeAll, cancelClose, cancelOpen]);

  // Dismiss the popover when the operator interacts anywhere outside the
  // rail (content area, header, deck). Without this a pinned popover -
  // e.g. after a keyboard toggle - could linger over the content even
  // once the operator has clicked away.
  useEffect(() => {
    if (state.group === null) return;
    const onPointerDown = (e: PointerEvent) => {
      const target = e.target as Node | null;
      if (navRef.current && target && !navRef.current.contains(target)) {
        closeAll();
      }
    };
    window.addEventListener("pointerdown", onPointerDown);
    return () => window.removeEventListener("pointerdown", onPointerDown);
  }, [state.group, closeAll]);

  const focusGroupBy = useCallback(
    (from: PanelGroup, delta: number) => {
      const idx = PANEL_GROUPS.findIndex((g) => g.id === from);
      if (idx < 0) return;
      const next = PANEL_GROUPS[(idx + delta + PANEL_GROUPS.length) % PANEL_GROUPS.length];
      if (next === undefined) return;
      const el = iconRefs.current.get(next.id);
      el?.focus();
      openGroup(next.id);
    },
    [openGroup],
  );

  return (
    <nav ref={navRef} class="left-rail" aria-label="Primary navigation">
      <ul class="left-rail-list">
        {PANEL_GROUPS.map((g) => {
          const panels = panelsInGroup(g.id);
          if (panels.length === 0) return null;
          const isActiveGroup = activeGroup === g.id;
          const isOpen = state.group === g.id;
          const firstPanel = panels[0];
          return (
            <li key={g.id} class="left-rail-item">
              <button
                ref={(el) => {
                  iconRefs.current.set(g.id, el);
                }}
                type="button"
                class={`left-rail-icon ${isActiveGroup ? "left-rail-icon-active" : ""} ${isOpen ? "left-rail-icon-open" : ""}`}
                data-group={g.id}
                aria-label={`${g.label} - ${g.hint}`}
                aria-expanded={isOpen}
                aria-haspopup="true"
                onMouseEnter={() => scheduleOpen(g.id)}
                onMouseLeave={scheduleClose}
                onFocus={() => openGroup(g.id)}
                onBlur={scheduleClose}
                onClick={() => {
                  // Click on a group icon = jump to its first sub-panel.
                  // The popover stays open only while the pointer keeps
                  // hovering (NOT pinned) so it dismisses itself the
                  // moment the operator moves into the content or clicks
                  // away. A pinned-open click used to leave the flyout
                  // lingering over the content after navigation.
                  if (firstPanel && activePanelId !== firstPanel.id) {
                    window.location.hash = `#/${firstPanel.id}`;
                  }
                  openGroup(g.id);
                }}
                onKeyDown={(e) => {
                  if (e.key === "ArrowDown") {
                    e.preventDefault();
                    focusGroupBy(g.id, 1);
                  } else if (e.key === "ArrowUp") {
                    e.preventDefault();
                    focusGroupBy(g.id, -1);
                  } else if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    if (firstPanel) {
                      window.location.hash = `#/${firstPanel.id}`;
                      openGroup(g.id, { pin: true });
                    }
                  }
                }}
              >
                <span class="left-rail-glyph" aria-hidden="true">
                  {groupIcon(g.id)}
                </span>
                <span class="left-rail-label">{g.label}</span>
              </button>

              {isOpen ? (
                <RailPopover
                  group={g.id}
                  activePanelId={activePanelId}
                  onNavigate={closeAll}
                  onMouseEnter={cancelClose}
                  onMouseLeave={scheduleClose}
                />
              ) : null}
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

interface PopoverProps {
  readonly group: PanelGroup;
  readonly activePanelId: string;
  readonly onNavigate: () => void;
  readonly onMouseEnter: () => void;
  readonly onMouseLeave: () => void;
}

function RailPopover({
  group,
  activePanelId,
  onNavigate,
  onMouseEnter,
  onMouseLeave,
}: PopoverProps) {
  const panels = panelsInGroup(group);
  const meta = PANEL_GROUPS.find((g) => g.id === group);
  return (
    <div
      class="left-rail-popover"
      role="menu"
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
    >
      {meta ? (
        <header class="left-rail-popover-head">
          <span class="left-rail-popover-title">{meta.label}</span>
          <span class="left-rail-popover-hint muted">{meta.hint}</span>
        </header>
      ) : null}
      <ul class="left-rail-popover-list">
        {panels.map((p) => {
          const active = p.id === activePanelId;
          return (
            <li key={p.id}>
              <a
                href={`#/${p.id}`}
                class={`left-rail-popover-item ${active ? "left-rail-popover-item-active" : ""}`}
                role="menuitem"
                onClick={onNavigate}
              >
                <span class="left-rail-popover-item-label">{p.label}</span>
                {p.subtitle ? (
                  <span class="left-rail-popover-item-sub muted">{p.subtitle}</span>
                ) : null}
              </a>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
