/**
 * Two-step antesala:
 *   1. Enter server URL → verify /health → fetch /auth/config
 *   2. "Login with SSO" — always the only auth path.
 *      SSO goes through the server's identity broker (Keycloak), which
 *      federates any downstream provider: Google, LDAP, SAML, GitHub, etc.
 *      If OIDC is not yet enabled on the server, the button is shown disabled
 *      with a setup hint.
 */
import { useState } from "react";
import type { AuthConfig } from "../types";
import { serverApi, getAgentUrl } from "../api";
import { initOidc, resolveOidcIssuer, startLogin } from "../auth/oidc";
import Logo from "../components/Logo";
import OnlineBird from "../components/OnlineBird";
import { markIntroForPlayback } from "../intro";

type Phase = "server" | "auth";

export default function ConnectPage() {
  const [phase, setPhase] = useState<Phase>("server");
  const [serverUrl, setServerUrl] = useState(
    localStorage.getItem("serverUrl") ?? "http://localhost:8080"
  );
  const [authConfig, setAuthConfig] = useState<AuthConfig | null>(null);
  const [peerId, setPeerId] = useState(localStorage.getItem("peerId") ?? "peer-alice");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleServerConnect() {
    setError(null);
    setLoading(true);
    try {
      const url = serverUrl.replace(/\/$/, "");
      await serverApi.health(url);
      const cfg = await serverApi.authConfig(url);
      setAuthConfig(cfg);
      if (cfg.oidc_enabled && cfg.issuer && cfg.client_id) {
        const issuer = resolveOidcIssuer(url, cfg.issuer);
        // En Electron usamos el Agente como Loopback (http://127.0.0.1:8000/auth/callback)
        const redirectUri = window.rsAgent?.openExternal
          ? `${getAgentUrl()}/auth/callback` 
          : window.location.origin;
        initOidc(issuer, cfg.client_id, redirectUri);
      }
      setPhase("auth");
    } catch (e) {
      setError(`No se pudo conectar: ${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  }

  function handleDevJoin() {
    const url = serverUrl.replace(/\/$/, "");
    const id = peerId.trim();
    if (!id) {
      setError("Ingresá un Peer ID.");
      return;
    }
    localStorage.setItem("serverUrl", url);
    localStorage.setItem("peerId", id);
    localStorage.removeItem("token");
    markIntroForPlayback();
    window.location.reload();
  }

  async function handleSsoLogin() {
    if (!authConfig?.oidc_enabled) return;
    localStorage.setItem("serverUrl", serverUrl.replace(/\/$/, ""));
    setError(null);
    setLoading(true);
    try {
      const { handleLoopback } = await import("../auth/oidc");
      await startLogin();
      // Electron: el agente expone /auth/poll y espera el código del navegador externo.
      if (window.rsAgent?.openExternal) {
        const user = await handleLoopback();
        const peerId = user.profile.sub ?? "oidc-user";
        localStorage.setItem("peerId", peerId);
        localStorage.setItem("token", user.access_token ?? "");
        markIntroForPlayback();
        window.location.reload();
      }
      // Navegador: startLogin() ya redirige a Keycloak; al volver con code/state,
      // App.tsx detecta el callback y completa el flujo. No hay que esperar aquí.
    } catch (e) {
      setError(`Error al iniciar SSO: ${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  }

  const realmLabel = authConfig?.issuer?.split("/realms/")[1] ?? null;
  const ssoReady = authConfig?.oidc_enabled === true;

  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <div className="w-full max-w-md">

        {/* Logo */}
        <div className="text-center mb-10">
          <div className="mb-3 flex justify-center">
            <Logo size="lg" />
          </div>
          <p className="text-slate-400 text-base">P2P · Reed-Solomon FEC · Adaptive redundancy</p>
        </div>

        <div className="bird-panel rounded-2xl p-8 shadow-2xl">

          {/* ── Step 1: server URL ── */}
          {phase === "server" && (
            <>
              <h2 className="font-medium mb-1">Conectar al servidor</h2>
              <p className="text-slate-500 text-sm mb-6">Ingresá la URL del servidor de tu organización.</p>
              <label className="block mb-1 text-base text-slate-400">Server URL</label>
              <input
                type="url"
                value={serverUrl}
                onChange={(e) => setServerUrl(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleServerConnect()}
                placeholder="https://rs.miempresa.com"
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-4 py-2.5 text-base text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-brand-500 mb-5"
              />
              {error && (
                <p className="text-red-400 text-xs mb-4 bg-red-950/40 border border-red-900 rounded-lg px-3 py-2">
                  {error}
                </p>
              )}
              <button
                onClick={handleServerConnect}
                disabled={loading || !serverUrl.trim()}
                className="bird-btn w-full bg-brand-600 hover:bg-brand-700 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded-lg py-2.5 text-base font-medium transition-colors"
              >
                {loading ? "Verificando…" : "Continuar"}
              </button>
            </>
          )}

          {/* ── Step 2: SSO login ── */}
          {phase === "auth" && authConfig && (
            <>
              {/* Connected server pill */}
              <div className="flex items-center gap-2 mb-8">
                <OnlineBird variant={0} size="xs" />
                <span className="text-sm text-slate-300 truncate">{serverUrl.replace(/\/$/, "")}</span>
                <button
                  onClick={() => { setPhase("server"); setError(null); }}
                  className="ml-auto text-xs text-slate-500 hover:text-slate-300 flex-shrink-0"
                >
                  cambiar
                </button>
              </div>

              {ssoReady ? (
                <>
                  <h2 className="font-medium mb-1">Iniciar sesión</h2>
                  <p className="text-slate-500 text-sm mb-6">
                    Tu identidad es gestionada por el proveedor corporativo de tu organización.
                  </p>

                  {error && (
                    <p className="text-red-400 text-xs mb-4 bg-red-950/40 border border-red-900 rounded-lg px-3 py-2">
                      {error}
                    </p>
                  )}

                  <button
                    onClick={handleSsoLogin}
                    disabled={loading}
                    className="w-full flex items-center justify-center gap-3 bg-white hover:bg-slate-100 disabled:opacity-40 disabled:cursor-not-allowed text-slate-900 rounded-lg py-3 text-base font-semibold transition-colors mb-4"
                  >
                    <svg className="w-4 h-4 flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
                    </svg>
                    Login with SSO
                    {realmLabel && (
                      <span className="ml-auto text-xs font-normal text-slate-500 truncate max-w-28">
                        {realmLabel}
                      </span>
                    )}
                  </button>

                  <div className="flex items-center gap-2 mt-2">
                    <div className="flex-1 h-px bg-slate-800" />
                    <span className="text-xs text-slate-600">soporta</span>
                    <div className="flex-1 h-px bg-slate-800" />
                  </div>
                  <div className="flex justify-center gap-3 mt-3 flex-wrap">
                    {["Keycloak", "Google", "LDAP", "SAML", "GitHub"].map((p) => (
                      <span key={p} className="text-xs text-slate-600 bg-slate-800/60 rounded px-2 py-0.5">
                        {p}
                      </span>
                    ))}
                  </div>
                </>
              ) : (
                <>
                  <h2 className="font-medium mb-1">Modo desarrollo</h2>
                  <p className="text-slate-500 text-sm mb-6">
                    Sin SSO en este servidor. Elegí un nombre para identificarte en la red.
                  </p>

                  {error && (
                    <p className="text-red-400 text-xs mb-4 bg-red-950/40 border border-red-900 rounded-lg px-3 py-2">
                      {error}
                    </p>
                  )}

                  <label className="block mb-1 text-base text-slate-400">Peer ID</label>
                  <input
                    type="text"
                    value={peerId}
                    onChange={(e) => setPeerId(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && handleDevJoin()}
                    placeholder="peer-alice"
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-4 py-2.5 text-base text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-brand-500 mb-5 font-mono"
                  />

                  <button
                    onClick={handleDevJoin}
                    disabled={!peerId.trim()}
                    className="bird-btn w-full bg-brand-600 hover:bg-brand-700 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded-lg py-2.5 text-base font-medium transition-colors"
                  >
                    Entrar
                  </button>

                  <p className="mt-4 text-xs text-slate-600 text-center">
                    Usá el mismo ID que tenga el agente en su <code className="text-slate-500">.env</code> (por defecto <code className="text-slate-500">peer-alice</code>).
                  </p>
                </>
              )}

              <p className="mt-6 text-center text-xs text-slate-700">
                Agent:{" "}
                <span className="text-slate-600 font-mono">{getAgentUrl()}</span>
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
