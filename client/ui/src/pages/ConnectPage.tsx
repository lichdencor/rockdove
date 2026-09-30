/**
 * Two-step antesala:
 *   1. Enter server URL → verify /health → fetch /auth/config
 *   2. "Login with SSO" — always the only auth path.
 */
import { useEffect, useRef, useState } from "react";
import type { AuthConfig } from "../types";
import { serverApi, agentApi, getAgentUrl } from "../api";
import { initOidc, startLogin } from "../auth/oidc";
import TitleBar from "../components/TitleBar";

type Phase = "server" | "auth";

const HISTORY_KEY = "serverHistory";
const HISTORY_MAX = 5;

function loadHistory(): string[] {
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function saveHistory(history: string[]): void {
  localStorage.setItem(HISTORY_KEY, JSON.stringify(history));
}

function addToHistory(history: string[], url: string): string[] {
  const deduped = history.filter((h) => h !== url);
  return [url, ...deduped].slice(0, HISTORY_MAX);
}

export default function ConnectPage() {
  const [phase, setPhase] = useState<Phase>("server");
  const [serverUrl, setServerUrl] = useState(
    localStorage.getItem("serverUrl") ?? "http://localhost:8080"
  );
  const [authConfig, setAuthConfig] = useState<AuthConfig | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [history, setHistory] = useState<string[]>(() => loadHistory());
  const [historyOpen, setHistoryOpen] = useState(false);
  const comboRef = useRef<HTMLDivElement>(null);

  // Close dropdown on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (comboRef.current && !comboRef.current.contains(e.target as Node)) {
        setHistoryOpen(false);
      }
    }
    if (historyOpen) document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [historyOpen]);

  async function handleServerConnect() {
    setError(null);
    setLoading(true);
    setHistoryOpen(false);
    try {
      const url = serverUrl.replace(/\/$/, "");
      await serverApi.health(url);
      const cfg = await serverApi.authConfig(url);
      setAuthConfig(cfg);
      if (cfg.oidc_enabled && cfg.issuer && cfg.client_id) {
        const redirectUri = window.rsAgent?.openExternal
          ? `${getAgentUrl()}/auth/callback`
          : window.location.origin;
        initOidc(cfg.issuer, cfg.client_id, redirectUri);
      }
      const newHistory = addToHistory(history, url);
      setHistory(newHistory);
      saveHistory(newHistory);
      setPhase("auth");
    } catch (e) {
      setError(`No se pudo conectar: ${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  }

  function handleRemoveHistory(url: string, e: React.MouseEvent) {
    e.stopPropagation();
    const newHistory = history.filter((h) => h !== url);
    setHistory(newHistory);
    saveHistory(newHistory);
    if (newHistory.length === 0) setHistoryOpen(false);
  }

  function handleSelectHistory(url: string) {
    setServerUrl(url);
    setHistoryOpen(false);
  }

  async function handleSsoLogin() {
    if (!authConfig?.oidc_enabled) return;
    localStorage.setItem("serverUrl", serverUrl.replace(/\/$/, ""));
    setError(null);
    setLoading(true);
    try {
      const { handleLoopback } = await import("../auth/oidc");
      await startLogin();
      const user = await handleLoopback();
      const peerId = (user.profile as any).preferred_username ?? user.profile.sub ?? "oidc-user";
      localStorage.setItem("peerId", peerId);
      localStorage.setItem("token", user.access_token ?? "");
      await agentApi.setToken(user.access_token ?? "").catch(() => {});
      window.location.reload();
    } catch (e) {
      setError(`Error al iniciar SSO: ${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  }

  const realmLabel = authConfig?.issuer?.split("/realms/")[1] ?? null;
  const ssoReady = authConfig?.oidc_enabled === true;

  return (
    <div className="flex flex-col min-h-screen bg-slate-950">
      <TitleBar />
      <div className="flex-1 flex items-center justify-center px-4">
        <div className="w-full max-w-md">

          {/* Logo */}
          <div className="text-center mb-10">
            <div className="inline-flex items-center gap-3 text-brand-500 mb-3">
              <svg className="w-10 h-10" viewBox="0 0 24 24" fill="currentColor">
                <path d="M21 5c-2-2-5-2-7 0l-3 4c-1-1-3-1-5 1l-1 2 3-1c1 2 3 3 5 2l1 3-1 4 3-2-1-4c2-1 4-3 4-6l2-2v-1z"/>
                <circle cx="17" cy="6" r="1.2" fill="#0f172a"/>
              </svg>
              <span className="text-2xl font-semibold tracking-tight">RockDove</span>
            </div>
            <p className="text-slate-400 text-sm">P2P · Reed-Solomon FEC · Adaptive redundancy</p>
          </div>

          <div className="bg-slate-900 rounded-2xl border border-slate-800 p-8 shadow-2xl">

            {/* ── Step 1: server URL ── */}
            {phase === "server" && (
              <>
                <h2 className="text-lg font-medium mb-1">Conectar al servidor</h2>
                <p className="text-slate-500 text-xs mb-6">Ingresá la URL del servidor de tu organización.</p>

                <label className="block mb-1 text-sm text-slate-400">Server URL</label>

                {/* Combobox: input + history dropdown */}
                <div ref={comboRef} className="relative mb-5">
                  <input
                    type="url"
                    value={serverUrl}
                    onChange={(e) => setServerUrl(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && handleServerConnect()}
                    placeholder="https://rs.miempresa.com"
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-4 py-2.5 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-brand-500 pr-10"
                  />

                  {/* History toggle button */}
                  {history.length > 0 ? (
                    <button
                      type="button"
                      onClick={() => setHistoryOpen((v) => !v)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300 transition-colors"
                      title="Servidores conocidos"
                    >
                      <svg
                        className={`w-4 h-4 transition-transform duration-150 ${historyOpen ? "rotate-180" : ""}`}
                        viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                        strokeLinecap="round" strokeLinejoin="round"
                      >
                        <polyline points="6 9 12 15 18 9" />
                      </svg>
                    </button>
                  ) : null}

                  {/* Dropdown list */}
                  {historyOpen && history.length > 0 ? (
                    <div className="absolute z-20 left-0 right-0 top-full mt-1 bg-slate-900 border border-slate-700 rounded-xl overflow-hidden shadow-2xl">
                      <p className="px-3 pt-2.5 pb-1 text-xs text-slate-600 font-medium">Servidores conocidos</p>
                      {history.map((h) => (
                        <div
                          key={h}
                          className="flex items-center gap-2 px-3 py-2.5 hover:bg-slate-800 group cursor-pointer"
                          onClick={() => handleSelectHistory(h)}
                        >
                          {/* Globe icon */}
                          <svg className="w-3.5 h-3.5 text-slate-600 flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <circle cx="12" cy="12" r="10"/>
                            <line x1="2" y1="12" x2="22" y2="12"/>
                            <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>
                          </svg>
                          <span className="flex-1 text-xs font-mono text-slate-300 truncate">{h}</span>
                          {/* Trash icon */}
                          <button
                            type="button"
                            onClick={(e) => handleRemoveHistory(h, e)}
                            className="opacity-0 group-hover:opacity-100 transition-opacity text-slate-600 hover:text-red-400 p-0.5 rounded"
                            title="Eliminar"
                          >
                            <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                              <polyline points="3 6 5 6 21 6"/>
                              <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>
                              <path d="M10 11v6M14 11v6"/>
                              <path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>
                            </svg>
                          </button>
                        </div>
                      ))}
                    </div>
                  ) : null}
                </div>

                {error && (
                  <p className="text-red-400 text-xs mb-4 bg-red-950/40 border border-red-900 rounded-lg px-3 py-2">
                    {error}
                  </p>
                )}
                <button
                  onClick={handleServerConnect}
                  disabled={loading || !serverUrl.trim()}
                  className="w-full bg-brand-600 hover:bg-brand-700 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded-lg py-2.5 text-sm font-medium transition-colors"
                >
                  {loading ? "Verificando…" : "Continuar"}
                </button>
              </>
            )}

            {/* ── Step 2: SSO login ── */}
            {phase === "auth" && authConfig ? (
              <>
                {/* Connected server pill */}
                <div className="flex items-center gap-2 mb-8">
                  <div className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse flex-shrink-0" />
                  <span className="text-sm text-slate-300 truncate">{serverUrl.replace(/\/$/, "")}</span>
                  <button
                    onClick={() => { setPhase("server"); setError(null); }}
                    className="ml-auto text-xs text-slate-500 hover:text-slate-300 flex-shrink-0"
                  >
                    cambiar
                  </button>
                </div>

                <h2 className="text-lg font-medium mb-1">Iniciar sesión</h2>
                <p className="text-slate-500 text-xs mb-6">
                  Tu identidad es gestionada por el proveedor corporativo de tu organización.
                </p>

                {error && (
                  <p className="text-red-400 text-xs mb-4 bg-red-950/40 border border-red-900 rounded-lg px-3 py-2">
                    {error}
                  </p>
                )}

                {/* SSO button */}
                <button
                  onClick={handleSsoLogin}
                  disabled={!ssoReady}
                  className="w-full flex items-center justify-center gap-3 bg-white hover:bg-slate-100 disabled:bg-slate-800 disabled:border disabled:border-slate-700 disabled:cursor-not-allowed text-slate-900 disabled:text-slate-500 rounded-lg py-3 text-sm font-semibold transition-colors mb-4"
                >
                  <svg className="w-4 h-4 flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
                  </svg>
                  Login with SSO
                  {realmLabel ? (
                    <span className="ml-auto text-xs font-normal text-slate-500 truncate max-w-28">
                      {realmLabel}
                    </span>
                  ) : null}
                </button>

                {!ssoReady ? (
                  <div className="flex items-start gap-2 bg-amber-950/30 border border-amber-900/50 rounded-lg px-3 py-2.5 text-xs text-amber-400 mb-4">
                    <svg className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
                    </svg>
                    <span>
                      SSO no configurado en este servidor.
                      Activá <code className="text-amber-300">OIDC_ENABLED=true</code> para continuar.
                    </span>
                  </div>
                ) : null}

                {/* Provider hints */}
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

                <p className="mt-6 text-center text-xs text-slate-700">
                  Agent:{" "}
                  <span className="text-slate-600 font-mono">{getAgentUrl()}</span>
                </p>
              </>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
