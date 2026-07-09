import type { AuthContext } from "../auth";

/**
 * Sign-in screen. A deep-space nebula backdrop (pure CSS, no assets) with a
 * centered glass card carrying the FDAI mark and the Entra sign-in button.
 * The nebula layers are decorative (`aria-hidden`) and honour
 * `prefers-reduced-motion`.
 */
export function LoginRoute({ auth }: { readonly auth: AuthContext }) {
  return (
    <div class="login-cosmos">
      <div class="login-sky" aria-hidden="true">
        <span class="neb neb-a" />
        <span class="neb neb-b" />
        <span class="neb neb-c" />
        <span class="login-stars login-stars-far" />
        <span class="login-stars login-stars-near" />
      </div>

      <main class="login-card" role="main">
        <div class="login-mark" aria-hidden="true">
          <svg viewBox="0 0 64 64" width="48" height="48">
            <defs>
              <radialGradient id="fdai-core" cx="50%" cy="50%" r="50%">
                <stop offset="0%" stop-color="#cfe4ff" />
                <stop offset="55%" stop-color="#4f9df5" />
                <stop offset="100%" stop-color="#2b7fe0" />
              </radialGradient>
            </defs>
            {/* orbital rings + a bright core - a small constellation glyph */}
            <ellipse
              cx="32"
              cy="32"
              rx="26"
              ry="11"
              fill="none"
              stroke="currentColor"
              stroke-width="1.4"
              opacity="0.55"
              transform="rotate(-24 32 32)"
            />
            <ellipse
              cx="32"
              cy="32"
              rx="26"
              ry="11"
              fill="none"
              stroke="currentColor"
              stroke-width="1.4"
              opacity="0.35"
              transform="rotate(38 32 32)"
            />
            <circle cx="32" cy="32" r="8" fill="url(#fdai-core)" />
            <circle cx="9" cy="24" r="1.6" fill="currentColor" />
            <circle cx="54" cy="41" r="1.4" fill="currentColor" />
            <circle cx="44" cy="12" r="1.2" fill="currentColor" />
          </svg>
        </div>

        <h1 class="login-title">FDAI Console</h1>
        <p class="login-subtitle">Autonomous cloud operations control plane</p>

        <button
          type="button"
          class="login-signin"
          onClick={() => {
            void auth.signIn();
          }}
        >
          <svg viewBox="0 0 21 21" width="18" height="18" aria-hidden="true">
            <rect x="1" y="1" width="9" height="9" fill="#f25022" />
            <rect x="11" y="1" width="9" height="9" fill="#7fba00" />
            <rect x="1" y="11" width="9" height="9" fill="#00a4ef" />
            <rect x="11" y="11" width="9" height="9" fill="#ffb900" />
          </svg>
          <span>Sign in with Entra ID</span>
        </button>

        <p class="login-foot">
          Read-only operator console. Changes are delivered as remediation PRs
          and high-risk actions require human approval.
        </p>
      </main>
    </div>
  );
}
