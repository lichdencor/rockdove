import { useCallback, useEffect, useState } from "react";
import type { AgentConfig } from "../../types";
import { agentApi, serverApi } from "../../api";

interface Props {
  peerId: string;
  agentUrl: string;
  serverUrl: string;
}

const TRANSPORT_BADGE: Record<string, string> = {
  quic: "text-violet-400 bg-violet-950/50 border-violet-800",
  udp: "text-slate-500 bg-slate-800/50 border-slate-700",
};

interface HealthInfo {
  status: string;
  transport?: string;
  udp_host?: string;
  udp_port?: number;
}

function InfoRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex justify-between text-sm gap-4">
      <span className="text-slate-400 flex-shrink-0">{label}</span>
      <span className="text-slate-200 font-mono text-right truncate">{children}</span>
    </div>
  );
}

const appVersion =
  (import.meta as unknown as { env: Record<string, string> }).env.VITE_APP_VERSION ?? "1.1.0";

export default function ConfigTab({ agentUrl, serverUrl: _serverUrl }: Props) {
  // Live health state
  const [health, setHealth] = useState<HealthInfo | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);

  // Config form state
  const [config, setConfig] = useState<AgentConfig | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [form, setForm] = useState<Partial<AgentConfig>>({});
  const [saving, setSaving] = useState(false);
  const [saveResult, setSaveResult] = useState<{ ok: boolean; requires_restart: boolean } | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [showToken, setShowToken] = useState(false);

  // Ping state
  const [pinging, setPinging] = useState(false);
  const [pingMs, setPingMs] = useState<number | null>(null);
  const [pingError, setPingError] = useState<string | null>(null);

  const loadHealth = useCallback(async () => {
    try {
      const h = await agentApi.health();
      setHealth(h as HealthInfo);
      setHealthError(null);
    } catch (e) {
      setHealthError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    loadHealth();
  }, [loadHealth]);

  useEffect(() => {
    agentApi
      .getConfig()
      .then((cfg) => {
        setConfig(cfg);
        setForm(cfg);
      })
      .catch((e) => setLoadError((e as Error).message));
  }, []);

  function setField<K extends keyof AgentConfig>(key: K, val: AgentConfig[K]) {
    setForm((prev) => ({ ...prev, [key]: val }));
    setSaveResult(null);
    setSaveError(null);
  }

  async function handleSave() {
    setSaving(true);
    setSaveResult(null);
    setSaveError(null);
    try {
      const res = await agentApi.setConfig(form);
      setSaveResult({ ok: res.ok, requires_restart: res.requires_restart });
      setConfig((prev) =>
        prev
          ? { ...prev, ...form, transport_mode: res.transport_mode as "udp" | "quic" }
          : prev
      );
    } catch (e) {
      setSaveError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  async function handlePing() {
    setPinging(true);
    setPingMs(null);
    setPingError(null);
    const t0 = performance.now();
    try {
      await serverApi.health(form.server_url ?? _serverUrl);
      setPingMs(Math.round(performance.now() - t0));
    } catch (e) {
      setPingError((e as Error).message);
    } finally {
      setPinging(false);
    }
  }

  const liveTransport = (health as HealthInfo | null)?.transport;
  const transportBadge = liveTransport
    ? TRANSPORT_BADGE[liveTransport.toLowerCase()] ?? TRANSPORT_BADGE.udp
    : null;

  const inputClass =
    "w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-sm text-slate-100 placeholder-slate-600 focus:outline-none focus:ring-1 focus:ring-brand-500";
  const labelClass = "text-xs text-slate-400 mb-1 block";
  const sectionHeaderClass =
    "text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3";
  const sectionCardClass =
    "bg-slate-800/40 rounded-lg border border-slate-700/50 p-4 space-y-3";

  return (
    <div className="space-y-4 overflow-auto h-full">
      {loadError ? (
        <p className="text-xs text-red-400 bg-red-950/40 border border-red-900 rounded-lg px-3 py-2">
          Error al cargar la configuración: {loadError}
        </p>
      ) : null}

      {/* Identidad */}
      <section>
        <h3 className={sectionHeaderClass}>Identidad</h3>
        <div className={sectionCardClass}>
          <div>
            <label className={labelClass} htmlFor="cfg-peer-id">Peer ID</label>
            <input
              id="cfg-peer-id"
              type="text"
              className={inputClass}
              value={form.peer_id ?? ""}
              onChange={(e) => setField("peer_id", e.target.value)}
              disabled={!config}
            />
          </div>

          <div>
            <label className={labelClass} htmlFor="cfg-agent-api-url">Agent API URL</label>
            <input
              id="cfg-agent-api-url"
              type="text"
              className={inputClass}
              value={form.agent_api_url ?? ""}
              onChange={(e) => setField("agent_api_url", e.target.value)}
              placeholder="auto-detectado"
              disabled={!config}
            />
            <p className="text-xs text-slate-500 mt-1">
              URL de este agente registrada con el servidor. Vacío = auto-detectado.
            </p>
          </div>

          <InfoRow label="Agent URL local">{agentUrl}</InfoRow>
          <InfoRow label="Versión">{appVersion}</InfoRow>
        </div>
      </section>

      {/* Estado del agente (live health, display-only) */}
      <section>
        <h3 className={sectionHeaderClass}>Agente</h3>
        <div className={sectionCardClass}>
          {healthError ? (
            <p className="text-xs text-red-400 bg-red-950/40 border border-red-900 rounded-lg px-3 py-2">
              {healthError}
            </p>
          ) : null}

          <div className="flex justify-between text-sm gap-4 items-center">
            <span className="text-slate-400 flex-shrink-0">Transport</span>
            <span>
              {transportBadge && liveTransport ? (
                <span className={`text-xs font-mono border rounded px-1.5 py-0.5 ${transportBadge}`}>
                  {liveTransport.toUpperCase()}
                </span>
              ) : (
                <span className="text-slate-500 font-mono text-sm">—</span>
              )}
            </span>
          </div>

          <InfoRow label="UDP Host">
            {(health as HealthInfo | null)?.udp_host ?? "—"}
          </InfoRow>
          <InfoRow label="UDP Port">
            {(health as HealthInfo | null)?.udp_port != null
              ? String((health as HealthInfo).udp_port)
              : "—"}
          </InfoRow>

          {liveTransport === "udp" ? (
            <div className="mt-2 flex items-start gap-2 bg-slate-800/40 border border-slate-700/50 rounded-lg px-3 py-2.5 text-xs text-slate-500">
              <svg
                className="w-3.5 h-3.5 flex-shrink-0 mt-px text-slate-600"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="8" x2="12" y2="12" />
                <line x1="12" y1="16" x2="12.01" y2="16" />
              </svg>
              <span>
                Para habilitar QUIC/TLS, cambiá el transport en la sección "Red P2P" y guardá.
              </span>
            </div>
          ) : null}
        </div>
      </section>

      {/* Servidor */}
      <section>
        <h3 className={sectionHeaderClass}>Servidor</h3>
        <div className={sectionCardClass}>
          <div>
            <label className={labelClass} htmlFor="cfg-server-url">Server URL</label>
            <input
              id="cfg-server-url"
              type="text"
              className={inputClass}
              value={form.server_url ?? ""}
              onChange={(e) => setField("server_url", e.target.value)}
              disabled={!config}
            />
          </div>

          <div className="flex items-center justify-between gap-4">
            <span className="text-sm text-slate-400">Latencia</span>
            <div className="flex items-center gap-3">
              {pingMs !== null ? (
                <span className="text-sm font-mono text-emerald-400">{pingMs} ms</span>
              ) : null}
              {pingError ? (
                <span className="text-xs text-red-400 font-mono">{pingError}</span>
              ) : null}
              <button
                onClick={handlePing}
                disabled={pinging}
                className="text-xs bg-slate-700 hover:bg-slate-600 disabled:opacity-40 text-slate-300 rounded-lg px-3 py-1.5 transition-colors"
              >
                {pinging ? "Midiendo…" : "Ping"}
              </button>
            </div>
          </div>
        </div>
      </section>

      {/* Red P2P */}
      <section>
        <h3 className={sectionHeaderClass}>Red P2P</h3>
        <div className={sectionCardClass}>
          {/* Transport toggle */}
          <div>
            <label className={labelClass}>Modo de transporte</label>
            <div className="flex gap-2">
              {(["udp", "quic"] as const).map((mode) => (
                <button
                  key={mode}
                  type="button"
                  disabled={!config}
                  onClick={() => {
                    setField("transport_mode", mode);
                  }}
                  className={`flex-1 py-2 text-xs font-mono rounded-lg border transition-colors ${
                    form.transport_mode === mode
                      ? mode === "quic"
                        ? "bg-violet-900/60 border-violet-700 text-violet-300"
                        : "bg-slate-700 border-slate-600 text-slate-200"
                      : "bg-slate-800/40 border-slate-700/50 text-slate-500 hover:text-slate-300 hover:border-slate-600 disabled:opacity-40 disabled:cursor-not-allowed"
                  }`}
                >
                  {mode.toUpperCase()}
                </button>
              ))}
            </div>
          </div>

          {/* QUIC warning */}
          {form.transport_mode === "quic" ? (
            <div className="flex items-start gap-2 bg-amber-950/30 border border-amber-800/50 rounded-lg px-3 py-2.5 text-xs text-amber-400">
              <svg
                className="w-3.5 h-3.5 flex-shrink-0 mt-px"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
                <line x1="12" y1="9" x2="12" y2="13" />
                <line x1="12" y1="17" x2="12.01" y2="17" />
              </svg>
              <span>
                QUIC requiere certificados TLS. Asegurate de que el agente esté configurado con los certs correspondientes.
              </span>
            </div>
          ) : null}

          <div>
            <label className={labelClass} htmlFor="cfg-udp-host">UDP Bind Host</label>
            <input
              id="cfg-udp-host"
              type="text"
              className={inputClass}
              value={form.udp_host ?? ""}
              onChange={(e) => setField("udp_host", e.target.value)}
              placeholder="0.0.0.0"
              disabled={!config}
            />
          </div>

          <div>
            <label className={labelClass} htmlFor="cfg-udp-port">UDP Port</label>
            <input
              id="cfg-udp-port"
              type="number"
              className={inputClass}
              value={form.udp_port ?? ""}
              onChange={(e) => setField("udp_port", Number(e.target.value))}
              disabled={!config}
            />
          </div>

          <div>
            <label className={labelClass} htmlFor="cfg-udp-advertise-host">Advertise Host</label>
            <input
              id="cfg-udp-advertise-host"
              type="text"
              className={inputClass}
              value={form.udp_advertise_host ?? ""}
              onChange={(e) => setField("udp_advertise_host", e.target.value)}
              placeholder="auto-detectado"
              disabled={!config}
            />
            <p className="text-xs text-slate-500 mt-1">
              IP que se anuncia a otros peers. Útil con VPN o multi-homed.
            </p>
          </div>
        </div>
      </section>

      {/* Almacenamiento */}
      <section>
        <h3 className={sectionHeaderClass}>Almacenamiento</h3>
        <div className={sectionCardClass}>
          <div>
            <label className={labelClass} htmlFor="cfg-storage-path">Directorio de archivos</label>
            <input
              id="cfg-storage-path"
              type="text"
              className={inputClass}
              value={form.storage_path ?? ""}
              onChange={(e) => setField("storage_path", e.target.value)}
              disabled={!config}
            />
          </div>
          <span className="text-xs text-amber-400 bg-amber-950/30 border border-amber-800/50 rounded px-2 py-0.5 inline-flex items-center gap-1">
            <svg
              className="w-3 h-3 flex-shrink-0"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
              <line x1="12" y1="9" x2="12" y2="13" />
              <line x1="12" y1="17" x2="12.01" y2="17" />
            </svg>
            Requiere reinicio para aplicar
          </span>
        </div>
      </section>

      {/* Acceso */}
      <section>
        <h3 className={sectionHeaderClass}>Acceso</h3>
        <div className={sectionCardClass}>
          <div>
            <label className={labelClass} htmlFor="cfg-invite-token">Invite Token</label>
            <div className="relative">
              <input
                id="cfg-invite-token"
                type={showToken ? "text" : "password"}
                className={`${inputClass} pr-10`}
                value={form.invite_token ?? ""}
                onChange={(e) => setField("invite_token", e.target.value)}
                placeholder="token de acceso al servidor"
                disabled={!config}
              />
              <button
                type="button"
                onClick={() => setShowToken((v) => !v)}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300 transition-colors p-0.5"
                aria-label={showToken ? "Ocultar token" : "Mostrar token"}
              >
                {showToken ? (
                  <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94" />
                    <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19" />
                    <line x1="1" y1="1" x2="23" y2="23" />
                  </svg>
                ) : (
                  <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                    <circle cx="12" cy="12" r="3" />
                  </svg>
                )}
              </button>
            </div>
          </div>

          <div>
            <label className={labelClass} htmlFor="cfg-network-hint">Network Hint</label>
            <input
              id="cfg-network-hint"
              type="text"
              className={inputClass}
              value={form.network_hint ?? ""}
              onChange={(e) => setField("network_hint", e.target.value)}
              disabled={!config}
            />
          </div>
        </div>
      </section>

      {/* Save banners */}
      {saveResult ? (
        saveResult.requires_restart ? (
          <p className="text-xs text-amber-400 bg-amber-950/40 border border-amber-800 rounded-lg px-3 py-2">
            Configuración guardada. Reiniciá el agente para aplicar todos los cambios.
          </p>
        ) : (
          <p className="text-xs text-emerald-400 bg-emerald-950/40 border border-emerald-900 rounded-lg px-3 py-2">
            Configuración guardada.
          </p>
        )
      ) : null}

      {saveError ? (
        <p className="text-xs text-red-400 bg-red-950/40 border border-red-900 rounded-lg px-3 py-2">
          Error al guardar: {saveError}
        </p>
      ) : null}

      {/* Save button */}
      <button
        type="button"
        onClick={handleSave}
        disabled={saving || !config}
        className="w-full bg-brand-600 hover:bg-brand-700 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded-lg py-2.5 text-sm font-medium transition-colors"
      >
        {saving ? "Guardando…" : "Guardar configuración"}
      </button>
    </div>
  );
}
