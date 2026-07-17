import { useCallback, useEffect, useRef, useState } from "preact/hooks";

export function useTransientFlag(delayMs: number): readonly [boolean, () => void] {
  const [active, setActive] = useState(false);
  const mountedRef = useRef(true);
  const timerRef = useRef<number | null>(null);

  useEffect(() => () => {
    mountedRef.current = false;
    if (timerRef.current !== null) window.clearTimeout(timerRef.current);
  }, []);

  const activate = useCallback(() => {
    if (!mountedRef.current) return;
    setActive(true);
    if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(() => {
      timerRef.current = null;
      if (mountedRef.current) setActive(false);
    }, delayMs);
  }, [delayMs]);

  return [active, activate];
}
