import {
  autoUpdate,
  computePosition,
  flip,
  offset,
  shift,
  type Placement,
} from "@floating-ui/dom";
import { cloneElement, type ComponentChildren, type VNode } from "preact";
import { createPortal } from "preact/compat";
import { useEffect, useId, useLayoutEffect, useRef, useState } from "preact/hooks";

export const TOOLTIP_DELAY_MS = 100;
export const TOOLTIP_EXIT_MS = 50;

type TooltipState = "delayed-open" | "instant-open" | "closed";

interface TooltipProps {
  readonly children: VNode<{ readonly "aria-describedby"?: string }>;
  readonly content: ComponentChildren;
  readonly placement?: Placement;
  readonly delay?: number;
  readonly sideOffset?: number;
}

export function Tooltip({
  children,
  content,
  placement = "top",
  delay = TOOLTIP_DELAY_MS,
  sideOffset = 4,
}: TooltipProps) {
  const id = useId();
  const anchorRef = useRef<HTMLSpanElement | null>(null);
  const tooltipRef = useRef<HTMLSpanElement | null>(null);
  const openTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const closeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [state, setState] = useState<TooltipState | null>(null);
  const [position, setPosition] = useState({ x: 0, y: 0, placement });
  const [positioned, setPositioned] = useState(false);

  function clearTimer(timerRef: typeof openTimerRef): void {
    if (timerRef.current === null) return;
    clearTimeout(timerRef.current);
    timerRef.current = null;
  }

  function show(openDelay: number): void {
    clearTimer(openTimerRef);
    clearTimer(closeTimerRef);
    if (openDelay === 0) {
      setState("instant-open");
      return;
    }
    openTimerRef.current = setTimeout(() => {
      openTimerRef.current = null;
      setState("delayed-open");
    }, openDelay);
  }

  function hide(): void {
    clearTimer(openTimerRef);
    clearTimer(closeTimerRef);
    setState((current) => {
      if (current === null) return null;
      closeTimerRef.current = setTimeout(() => {
        closeTimerRef.current = null;
        setState(null);
        setPositioned(false);
      }, TOOLTIP_EXIT_MS);
      return "closed";
    });
  }

  useEffect(() => () => {
    clearTimer(openTimerRef);
    clearTimer(closeTimerRef);
  }, []);

  useLayoutEffect(() => {
    const anchor = anchorRef.current;
    const tooltip = tooltipRef.current;
    if (state === null || anchor === null || tooltip === null) return;

    let active = true;
    const update = () => {
      void computePosition(anchor, tooltip, {
        placement,
        strategy: "fixed",
        middleware: [
          offset(sideOffset),
          flip({ padding: 16 }),
          shift({ padding: 16 }),
        ],
      }).then((next) => {
        if (!active) return;
        setPosition({ x: next.x, y: next.y, placement: next.placement });
        setPositioned(true);
      });
    };
    const stopAutoUpdate = autoUpdate(anchor, tooltip, update);
    return () => {
      active = false;
      stopAutoUpdate();
    };
  }, [placement, sideOffset, state]);

  const describedTrigger = cloneElement(children, {
    "aria-describedby": state === null ? undefined : id,
  });
  const side = position.placement.split("-")[0];

  return (
    <span
      ref={anchorRef}
      class="tooltip-anchor"
      onPointerEnter={(event) => {
        if (event.pointerType !== "touch") show(delay);
      }}
      onPointerLeave={hide}
      onFocus={() => show(0)}
      onBlur={(event) => {
        if (!anchorRef.current?.contains(event.relatedTarget as Node | null)) hide();
      }}
      onClick={hide}
      onKeyDown={(event) => {
        if (event.key === "Escape") hide();
      }}
    >
      {describedTrigger}
      {state !== null && typeof document !== "undefined"
        ? createPortal(
            <span
              ref={tooltipRef}
              id={id}
              role="tooltip"
              class="app-tooltip"
              data-state={state}
              data-side={side}
              style={{
                left: `${position.x}px`,
                top: `${position.y}px`,
                visibility: positioned ? "visible" : "hidden",
              }}
            >
              {content}
            </span>,
            document.body,
          )
        : null}
    </span>
  );
}
