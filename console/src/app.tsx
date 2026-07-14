import { useEffect, useState } from "preact/hooks";
import { lazy, Suspense } from "preact/compat";
import { ReadApiClient } from "./api";
import type { AuthContext } from "./auth";
import { initAuth } from "./auth";
import { loadConfig, type ConsoleConfig } from "./config";
import { Shell } from "./components/shell";
import { PanelErrorBoundary } from "./components/panel-error-boundary";
import { setChatAuth } from "./deck/backend";
import { ViewContextProvider } from "./deck/context";
import { deckUserFromAuth, setDeckUser } from "./deck/deck-user";
import { setWorkflowAuth } from "./workflow/validate";
import { LoginRoute } from "./routes/login";
import { DEFAULT_PANEL_ID, panelForId, resolvePanels } from "./panels";
import {
  currentRoute,
  installNavigationListener,
  migrateLegacyHash,
  panelPath,
} from "./router";

interface AppState {
  readonly status: "loading" | "ready" | "error";
  readonly config?: ConsoleConfig;
  readonly auth?: AuthContext;
  readonly client?: ReadApiClient;
  readonly error?: string;
}

const CommandDeck = lazy(async () => {
  const module = await import("./deck/command-deck");
  return { default: module.CommandDeck };
});

function currentPanelId(): string {
  if (typeof window === "undefined") return DEFAULT_PANEL_ID;
  const route = currentRoute();
  const known = resolvePanels().some((panel) => panel.id === route.panelId);
  return known ? route.panelId : DEFAULT_PANEL_ID;
}

export function App() {
  const [state, setState] = useState<AppState>({ status: "loading" });
  const [panelId, setPanelId] = useState<string>(currentPanelId());
  const [routeKey, setRouteKey] = useState(() =>
    typeof window === "undefined" ? "/overview" : `${window.location.pathname}${window.location.search}`,
  );

  useEffect(() => {
    migrateLegacyHash();
    const route = currentRoute();
    if (window.location.pathname === "/" || !resolvePanels().some((p) => p.id === route.panelId)) {
      window.history.replaceState(null, "", panelPath(DEFAULT_PANEL_ID));
    }
    const syncRoute = () => {
      setPanelId(currentPanelId());
      setRouteKey(`${window.location.pathname}${window.location.search}`);
    };
    syncRoute();
    return installNavigationListener(syncRoute);
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const config = loadConfig();
        const auth = await initAuth(config);
        const client = new ReadApiClient(config, auth);
        // Expose the signed-in operator's roles to the chat deck so it can
        // answer capability questions ("what can I do?").
        setDeckUser(deckUserFromAuth(auth));
        // Thread the operator's bearer token to the workflow-builder's
        // validate POST (the one non-GET, read-only call the console makes).
        setWorkflowAuth(auth);
        setChatAuth(auth);
        if (!cancelled) {
          setState({ status: "ready", config, auth, client });
        }
      } catch (err) {
        if (!cancelled) {
          setState({
            status: "error",
            error: err instanceof Error ? err.message : String(err),
          });
        }
      }
    })();
    return () => {
      cancelled = true;
      setChatAuth(null);
    };
  }, []);

  if (state.status === "loading") {
    return <div class="empty">Loading...</div>;
  }

  if (state.status === "error") {
    return (
      <div class="empty error">
        <p>Console failed to initialize.</p>
        <p class="mono">{state.error}</p>
      </div>
    );
  }

  const { auth, client } = state;
  if (!auth || !client) {
    return <div class="empty error">Internal state missing.</div>;
  }

  if (!auth.devMode && !auth.account) {
    return <LoginRoute auth={auth} />;
  }

  const panel = panelForId(panelId);
  const PanelComponent = panel.component;

  return (
    <ViewContextProvider scopeKey={routeKey}>
      <Shell activePanelId={panel.id} auth={auth}>
        <PanelErrorBoundary key={routeKey}>
          <Suspense fallback={<div class="state-block state-loading" role="status">Loading panel...</div>}>
            <PanelComponent client={client} />
          </Suspense>
        </PanelErrorBoundary>
      </Shell>
      <CommandDeck />
    </ViewContextProvider>
  );
}
