import type { ComponentChildren } from "preact";
import { useEffect, useState } from "preact/hooks";
import type { AuthContext } from "../auth";
import { LeftRail } from "./left-rail";

interface ShellProps {
  readonly activePanelId: string;
  readonly auth: AuthContext;
  readonly children: ComponentChildren;
}

type Theme = "light" | "dark";
const THEME_STORAGE_KEY = "fdai:console:theme";

function readInitialTheme(): Theme {
  if (typeof window === "undefined") return "light";
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    if (stored === "light" || stored === "dark") return stored;
  } catch {
    // localStorage may be denied in private mode / iframe; fall through.
  }
  // Default is light per the initial mockup. We do NOT follow system
  // preference by default - operators expect a stable, predictable
  // console appearance across machines.
  return "light";
}

export function Shell({ activePanelId, auth, children }: ShellProps) {
  const [theme, setTheme] = useState<Theme>(readInitialTheme);

  useEffect(() => {
    if (typeof document === "undefined") return;
    document.documentElement.setAttribute("data-theme", theme);
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, theme);
    } catch {
      // storage denied - the DOM attribute is still applied for this session.
    }
  }, [theme]);

  const toggleTheme = () => setTheme((t) => (t === "dark" ? "light" : "dark"));

  return (
    <div class="shell">
      <header class="topbar">
        <h1 class="topbar-title">FDAI Console</h1>
        <div class="principal">
          <button
            type="button"
            class="theme-toggle"
            onClick={toggleTheme}
            aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
            title={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
          >
            {theme === "dark" ? (
              // sun icon (indicates the target: click to go light)
              <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
                <circle cx="8" cy="8" r="3" fill="currentColor" />
                <g stroke="currentColor" stroke-width="1.4" stroke-linecap="round">
                  <line x1="8" y1="1.5" x2="8" y2="3.5" />
                  <line x1="8" y1="12.5" x2="8" y2="14.5" />
                  <line x1="1.5" y1="8" x2="3.5" y2="8" />
                  <line x1="12.5" y1="8" x2="14.5" y2="8" />
                  <line x1="3.2" y1="3.2" x2="4.6" y2="4.6" />
                  <line x1="11.4" y1="11.4" x2="12.8" y2="12.8" />
                  <line x1="3.2" y1="12.8" x2="4.6" y2="11.4" />
                  <line x1="11.4" y1="4.6" x2="12.8" y2="3.2" />
                </g>
              </svg>
            ) : (
              // moon icon (indicates the target: click to go dark)
              <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
                <path
                  d="M13 10.2 A5.5 5.5 0 1 1 5.8 3 A4.5 4.5 0 0 0 13 10.2 Z"
                  fill="currentColor"
                />
              </svg>
            )}
          </button>
          {auth.devMode ? (
            <span class="badge">dev mode</span>
          ) : auth.account ? (
            <>
              <span>{auth.account.username}</span>
              <button
                type="button"
                onClick={() => {
                  void auth.signOut();
                }}
              >
                Sign out
              </button>
            </>
          ) : null}
        </div>
      </header>
      <div class="shell-body">
        <LeftRail activePanelId={activePanelId} />
        <main>{children}</main>
      </div>
    </div>
  );
}
