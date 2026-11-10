import { useCallback, useEffect, useRef, useState } from "react";
import { serverApi, getServerUrl } from "../api";
import type { DeviceTokenInfo, IncomingPolicyConfig, MetricHistory, NetworkEdge, PeerInfo, RelayConfig } from "../types";

// eslint-disable-next-line @typescript-eslint/no-empty-interface
interface Props {}

type Tab = "scopes" | "invites" | "device-tokens" | "relays" | "metrics" | "policies";

interface GeneratedInvite {
  token: string;
  deviceId: string;
  expiresAt: string;
}

// ── Scopes tab ────────────────────────────────────────────────────────────────

function ScopesTab() {
  const [scopes, setScopes] = useState<Record<string, string[]>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [newGroup, setNewGroup] = useState("");
  const [newVisible, setNewVisible] = useState("");

  useEffect(() => {
    serverApi
      .getScopes()
      .then((cfg) => setScopes(cfg.scopes))
      .catch((e) => setError(`Error cargando scopes: ${(e as Error).message}`))
      .finally(() => setLoading(false));
  }, []);

  async function save() {
    setSaving(true);
    setError(null);
    setSuccess(false);
    try {
      await serverApi.setScopes({ scopes });
      setSuccess(true);
      setTimeout(() => setSuccess(false), 2000);
    } catch (e) {
      setError(`Error guardando: ${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  }

  function addRule() {
    const group = newGroup.trim();
    if (!group) return;
    const visible = newVisible.split(",").map((s) => s.trim()).filter(Boolean);
    setScopes((prev) => ({ ...prev, [group]: visible }));
    setNewGroup("");
    setNewVisible("");
  }

  function removeRule(group: string) {
    setScopes((prev) => {
      const next = { ...prev };
      delete next[group];
      return next;
    });
  }

  function updateVisible(group: string, raw: string) {
    const visible = raw.split(",").map((s) => s.trim()).filter(Boolean);
    setScopes((prev) => ({ ...prev, [group]: visible }));
  }

  if (loading) return <p className="text-xs text-slate-500 py-4">Cargando…</p>;

  return (
    <div className="space-y-4">
      <p className="text-xs text-slate-500">
        Configurá qué grupos puede ver cada grupo dentro de esta org.
        Usá <code className="text-slate-400">__all__</code> para acceso total.
      </p>

      {error && (
        <p className="text-xs text-red-400 bg-red-950/40 border border-red-900 rounded-lg px-3 py-2">
          {error}
        </p>
      )}

      {Object.keys(scopes).length === 0 ? (
        <p className="text-xs text-slate-600 italic">
          Sin reglas — cada grupo ve sólo sus propios peers.
        </p>
      ) : (
        <table className="w-full text-xs">
          <thead>
            <tr className="text-slate-500 text-left">
              <th className="pb-2 font-medium w-1/3">Grupo</th>
              <th className="pb-2 font-medium">Puede ver (coma separado)</th>
              <th className="pb-2 w-6" />
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {Object.entries(scopes).map(([group, visible]) => (
              <tr key={group}>
                <td className="py-2 pr-3 font-mono text-slate-300">{group}</td>
                <td className="py-2 pr-2">
                  <input
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-2 py-1 text-slate-200 focus:outline-none focus:border-brand-500"
                    value={visible.join(", ")}
                    onChange={(e) => updateVisible(group, e.target.value)}
                  />
                </td>
                <td className="py-2">
                  <button
                    onClick={() => removeRule(group)}
                    className="text-slate-600 hover:text-red-400 transition-colors"
                  >
                    ✕
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <div className="border-t border-slate-800 pt-3">
        <p className="text-xs text-slate-500 mb-2">Nueva regla</p>
        <div className="flex gap-2">
          <input
            className="flex-1 bg-slate-800 border border-slate-700 rounded-lg px-2 py-1.5 text-xs text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-brand-500"
            placeholder="Grupo"
            value={newGroup}
            onChange={(e) => setNewGroup(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && addRule()}
          />
          <input
            className="flex-[2] bg-slate-800 border border-slate-700 rounded-lg px-2 py-1.5 text-xs text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-brand-500"
            placeholder="Grupos visibles (ej: hq, field) o __all__"
            value={newVisible}
            onChange={(e) => setNewVisible(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && addRule()}
          />
          <button
            onClick={addRule}
            className="text-xs bg-slate-700 hover:bg-slate-600 text-slate-200 rounded-lg px-3 py-1.5 transition-colors"
          >
            +
          </button>
        </div>
      </div>

      <div className="flex justify-end gap-3 pt-2">
        {success && <span className="text-xs text-emerald-400 self-center">Guardado</span>}
        <button
          onClick={save}
          disabled={saving}
          className="text-xs bg-brand-600 hover:bg-brand-700 disabled:opacity-40 text-white rounded-lg px-4 py-1.5 transition-colors"
        >
          {saving ? "Guardando…" : "Guardar cambios"}
        </button>
      </div>
    </div>
  );
}

// ── Invites tab ───────────────────────────────────────────────────────────────

function InvitesTab() {
  const [deviceId, setDeviceId] = useState("");
  const [ttlHours, setTtlHours] = useState(24);
  const [group, setGroup] = useState("field");
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [generated, setGenerated] = useState<GeneratedInvite | null>(null);

  async function generate() {
    const id = deviceId.trim() || `device-${Math.random().toString(36).slice(2, 8)}`;
    setGenerating(true);
    setError(null);
    try {
      const info = await serverApi.createInvite(ttlHours * 3600);
      setGenerated({ token: info.token, deviceId: id, expiresAt: info.expires_at });
      setDeviceId("");
    } catch (e) {
      setError(`Error generando invite: ${(e as Error).message}`);
    } finally {
      setGenerating(false);
    }
  }

  const serverUrl = getServerUrl();
  const envSnippet = generated
    ? `SERVER_URL=${serverUrl}\nPEER_ID=${generated.deviceId}\nINVITE_TOKEN=${generated.token}\nUDP_HOST=0.0.0.0\nUDP_PORT=9001\n`
    : "";

  return (
    <div className="space-y-4">
      <p className="text-xs text-slate-500">
        Generá un token de invitación para un agente headless (IoT, edge, CI).
        El token es de un solo uso — el agente lo consume al registrarse.
      </p>

      {error && (
        <p className="text-xs text-red-400 bg-red-950/40 border border-red-900 rounded-lg px-3 py-2">
          {error}
        </p>
      )}

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs text-slate-500 block mb-1">ID del dispositivo</label>
          <input
            className="w-full bg-slate-800 border border-slate-700 rounded-lg px-2 py-1.5 text-xs text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-brand-500"
            placeholder="ej: sensor-planta-1 (auto si vacío)"
            value={deviceId}
            onChange={(e) => setDeviceId(e.target.value)}
          />
        </div>
        <div>
          <label className="text-xs text-slate-500 block mb-1">Grupo</label>
          <input
            className="w-full bg-slate-800 border border-slate-700 rounded-lg px-2 py-1.5 text-xs text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-brand-500"
            placeholder="field"
            value={group}
            onChange={(e) => setGroup(e.target.value)}
          />
        </div>
        <div>
          <label className="text-xs text-slate-500 block mb-1">Expira en (horas)</label>
          <input
            type="number"
            min={1}
            max={720}
            className="w-full bg-slate-800 border border-slate-700 rounded-lg px-2 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-brand-500"
            value={ttlHours}
            onChange={(e) => setTtlHours(Number(e.target.value))}
          />
        </div>
      </div>

      <button
        onClick={generate}
        disabled={generating}
        className="text-xs bg-brand-600 hover:bg-brand-700 disabled:opacity-40 text-white rounded-lg px-4 py-1.5 transition-colors"
      >
        {generating ? "Generando…" : "Generar invite"}
      </button>

      {generated && (
        <div className="mt-4 space-y-2">
          <div className="flex items-center justify-between">
            <p className="text-xs text-slate-400 font-medium">
              Config para <span className="font-mono text-slate-300">{generated.deviceId}</span>
            </p>
            <button
              onClick={() => navigator.clipboard.writeText(envSnippet)}
              className="text-xs text-slate-500 hover:text-slate-300 bg-slate-800 hover:bg-slate-700 rounded px-2 py-0.5 transition-colors"
            >
              Copiar .env
            </button>
          </div>
          <pre className="bg-slate-950 border border-slate-800 rounded-lg p-3 text-xs font-mono text-slate-300 select-all whitespace-pre overflow-x-auto">
            {envSnippet}
          </pre>
          <p className="text-xs text-slate-600">
            El token expira {new Date(generated.expiresAt).toLocaleString()}.
            Pegá este .env en el agente headless y ejecutalo — el token se consume al primer registro.
          </p>
        </div>
      )}
    </div>
  );
}

// ── Device Tokens tab ─────────────────────────────────────────────────────────

function DeviceTokensTab() {
  const [label, setLabel] = useState("");
  const [peerId, setPeerId] = useState("");
  const [maxDays, setMaxDays] = useState("");   // "" = indefinido
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tokens, setTokens] = useState<DeviceTokenInfo[]>([]);
  const [loadingList, setLoadingList] = useState(true);
  const [created, setCreated] = useState<DeviceTokenInfo | null>(null);
  const [copied, setCopied] = useState(false);
  const [revoking, setRevoking] = useState<string | null>(null);

  useEffect(() => { void loadTokens(); }, []);

  async function loadTokens() {
    setLoadingList(true);
    try {
      const list = await serverApi.listDeviceTokens();
      setTokens(list);
    } catch {
      // lista vacía o sin permisos — silencioso
    } finally {
      setLoadingList(false);
    }
  }

  async function create() {
    if (!label.trim()) return;
    setCreating(true);
    setError(null);
    setCreated(null);
    try {
      const days = maxDays.trim() ? parseInt(maxDays, 10) : null;
      const info = await serverApi.createDeviceToken({
        label: label.trim(),
        peer_id: peerId.trim() || null,
        ttl_seconds: days ? days * 86400 : null,
      });
      setCreated(info);
      setLabel("");
      setPeerId("");
      setMaxDays("");
      await loadTokens();
    } catch (e) {
      setError(`Error creando token: ${(e as Error).message}`);
    } finally {
      setCreating(false);
    }
  }

  async function revoke(id: string) {
    setRevoking(id);
    setError(null);
    try {
      await serverApi.revokeDeviceToken(id);
      setTokens((prev) => prev.filter((t) => t.id !== id));
      if (created?.id === id) setCreated(null);
    } catch (e) {
      setError(`Error revocando: ${(e as Error).message}`);
    } finally {
      setRevoking(null);
    }
  }

  function copySnippet() {
    if (!created?.token) return;
    const serverUrl = getServerUrl();
    const pid = created.peer_id || created.label.toLowerCase().replace(/\s+/g, "-");
    const snippet = [
      `PEER_ID=${pid}`,
      `SERVER_URL=${serverUrl}`,
      `AGENT_API_URL=http://<device-ip>:8000`,
      `AGENT_SERVICE_TOKEN=${created.token}`,
    ].join("\n") + "\n";
    navigator.clipboard.writeText(snippet).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  function formatExpiry(t: DeviceTokenInfo) {
    if (!t.expires_at) return "∞ indefinido";
    return new Date(t.expires_at).toLocaleDateString("es-AR", {
      day: "2-digit", month: "short", year: "numeric",
    });
  }

  return (
    <div className="space-y-5">
      {/* ── Form ── */}
      <div className="space-y-3">
        <p className="text-xs text-slate-500">
          Cada dispositivo obtiene su propio token autogenerado. El valor completo
          sólo aparece al crearlo — guardalo antes de cerrar.
        </p>

        <div className="grid grid-cols-2 gap-3">
          <div className="col-span-2">
            <label className="text-xs text-slate-500 block mb-1">
              Etiqueta <span className="text-red-500">*</span>
            </label>
            <input
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-2 py-1.5 text-xs text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-brand-500"
              placeholder="ej: Sensor Planta A"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && create()}
            />
          </div>

          <div>
            <label className="text-xs text-slate-500 block mb-1">PEER_ID del dispositivo</label>
            <input
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-2 py-1.5 text-xs text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-brand-500"
              placeholder="ej: edge-01 (opcional)"
              value={peerId}
              onChange={(e) => setPeerId(e.target.value)}
            />
          </div>

          <div>
            <label className="text-xs text-slate-500 block mb-1">
              Máximo tiempo (días)
            </label>
            <input
              type="number"
              min={1}
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-2 py-1.5 text-xs text-slate-200 placeholder:text-slate-500 focus:outline-none focus:border-brand-500"
              placeholder="∞  sin vencimiento"
              value={maxDays}
              onChange={(e) => setMaxDays(e.target.value)}
            />
          </div>
        </div>

        {error && (
          <p className="text-xs text-red-400 bg-red-950/40 border border-red-900 rounded-lg px-3 py-2">
            {error}
          </p>
        )}

        <button
          onClick={create}
          disabled={creating || !label.trim()}
          className="text-xs bg-brand-600 hover:bg-brand-700 disabled:opacity-40 text-white rounded-lg px-4 py-1.5 transition-colors"
        >
          {creating ? "Generando…" : "Crear token"}
        </button>
      </div>

      {/* ── Token recién creado ── */}
      {created?.token && (
        <div className="rounded-xl border border-emerald-800/60 bg-emerald-950/30 p-4 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-emerald-400">
              Token creado — copialo ahora, no se vuelve a mostrar
            </span>
            <button
              onClick={copySnippet}
              className="text-xs text-slate-400 hover:text-slate-200 bg-slate-800 hover:bg-slate-700 rounded px-2 py-0.5 transition-colors"
            >
              {copied ? "¡Copiado!" : "Copiar .env"}
            </button>
          </div>
          <div className="space-y-1">
            <p className="text-xs text-slate-500">
              <span className="text-slate-400 font-medium">{created.label}</span>
              {created.peer_id && (
                <span className="ml-2 font-mono text-slate-500">{created.peer_id}</span>
              )}
              {created.expires_at ? (
                <span className="ml-2 text-slate-600">
                  · vence {new Date(created.expires_at).toLocaleDateString()}
                </span>
              ) : (
                <span className="ml-2 text-slate-600">· sin vencimiento</span>
              )}
            </p>
            <pre className="bg-slate-950 border border-slate-800 rounded-lg p-3 text-xs font-mono text-emerald-300 select-all whitespace-pre overflow-x-auto break-all">
              {created.token}
            </pre>
          </div>
        </div>
      )}

      {/* ── Lista de tokens activos ── */}
      <div className="space-y-2">
        <p className="text-xs text-slate-500 font-medium">Tokens activos</p>
        {loadingList ? (
          <p className="text-xs text-slate-600">Cargando…</p>
        ) : tokens.length === 0 ? (
          <p className="text-xs text-slate-600 italic">Sin tokens activos.</p>
        ) : (
          <div className="space-y-1.5">
            {tokens.map((t) => (
              <div
                key={t.id}
                className="flex items-center gap-3 bg-slate-800/50 border border-slate-800 rounded-lg px-3 py-2"
              >
                <div className="flex-1 min-w-0 space-y-0.5">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-medium text-slate-200 truncate">
                      {t.label}
                    </span>
                    {t.peer_id && (
                      <span className="text-xs font-mono text-slate-500 bg-slate-700/60 rounded px-1.5 py-0.5 shrink-0">
                        {t.peer_id}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-xs font-mono text-slate-600 truncate">
                      {t.token_preview}
                    </span>
                    <span className="text-xs text-slate-600 shrink-0">
                      {formatExpiry(t)}
                    </span>
                  </div>
                </div>
                <button
                  onClick={() => revoke(t.id)}
                  disabled={revoking === t.id}
                  title="Revocar token"
                  className="text-slate-600 hover:text-red-400 disabled:opacity-40 transition-colors shrink-0 text-sm leading-none"
                >
                  {revoking === t.id ? "…" : "✕"}
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Relays tab ────────────────────────────────────────────────────────────────

const RELAY_TAG_INFO: Record<string, { label: string; desc: string; color: string }> = {
  ephemeral: {
    label: "Efímero",
    desc: "Solo buffer RAM — nunca escribe a disco",
    color: "text-sky-400 bg-sky-950/50 border-sky-800",
  },
  restricted: {
    label: "Restringido",
    desc: "Solo peers/grupos autorizados pueden usarlo",
    color: "text-amber-400 bg-amber-950/50 border-amber-800",
  },
  gateway: {
    label: "Gateway",
    desc: "Rutas estáticas — ideal para satélite sin TCP al servidor",
    color: "text-violet-400 bg-violet-950/50 border-violet-800",
  },
};

const ALL_RELAY_TAGS = Object.keys(RELAY_TAG_INFO);

interface RelayPeerRowProps {
  peer: PeerInfo;
  onSaved: () => void;
}

function RelayPeerRow({ peer, onSaved }: RelayPeerRowProps) {
  const [expanded, setExpanded] = useState(false);
  const [capable, setCapable] = useState(peer.relay_capable ?? false);
  const [tags, setTags] = useState<string[]>(peer.relay_tags ?? []);
  const [allowedPeers, setAllowedPeers] = useState("");
  const [allowedGroups, setAllowedGroups] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  function toggleTag(tag: string) {
    setTags((prev) =>
      prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag]
    );
  }

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const cfg: RelayConfig = {
        relay_capable: capable,
        relay_tags: tags,
        relay_allowed_peers: allowedPeers.split(",").map((s) => s.trim()).filter(Boolean),
        relay_allowed_groups: allowedGroups.split(",").map((s) => s.trim()).filter(Boolean),
      };
      await serverApi.updateRelayConfig(peer.peer_id, cfg);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
      onSaved();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="border border-slate-700/60 rounded-xl overflow-hidden">
      {/* Row header */}
      <div
        className="flex items-center gap-3 px-4 py-3 bg-slate-800/30 cursor-pointer hover:bg-slate-800/50 transition-colors"
        onClick={() => setExpanded((v) => !v)}
      >
        <div className="flex-1 min-w-0 flex items-center gap-2">
          <span className="text-xs font-mono text-slate-200 truncate">{peer.peer_id}</span>
          <span className="text-[10px] text-slate-500">[{peer.group}]</span>
          <span className={`text-[9px] px-1 rounded ${peer.online ? "text-emerald-400" : "text-slate-600"}`}>
            {peer.online ? "● online" : "○ offline"}
          </span>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          {capable && (
            <span className="text-[10px] text-brand-400 bg-brand-950/50 border border-brand-800 rounded px-1.5 py-0.5">
              relay
            </span>
          )}
          {tags.map((t) => {
            const info = RELAY_TAG_INFO[t];
            return info ? (
              <span key={t} className={`text-[9px] border rounded px-1 py-0.5 ${info.color}`}>
                {info.label}
              </span>
            ) : null;
          })}
          <svg
            className={`w-3.5 h-3.5 text-slate-500 transition-transform ${expanded ? "rotate-180" : ""}`}
            viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
          >
            <polyline points="6 9 12 15 18 9" />
          </svg>
        </div>
      </div>

      {/* Expanded config */}
      {expanded && (
        <div className="px-4 py-4 border-t border-slate-700/60 space-y-4 bg-slate-900/20">
          {/* relay_capable toggle */}
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs font-medium text-slate-200">Relay activo</p>
              <p className="text-[10px] text-slate-500">Permite que otros peers usen este nodo como relay</p>
            </div>
            <button
              onClick={() => setCapable((v) => !v)}
              className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
                capable ? "bg-brand-600" : "bg-slate-700"
              }`}
            >
              <span
                className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${
                  capable ? "translate-x-4.5" : "translate-x-0.5"
                }`}
              />
            </button>
          </div>

          {/* Tags */}
          <div>
            <p className="text-xs font-medium text-slate-300 mb-2">Tags</p>
            <div className="space-y-2">
              {ALL_RELAY_TAGS.map((tag) => {
                const info = RELAY_TAG_INFO[tag];
                const active = tags.includes(tag);
                return (
                  <label key={tag} className="flex items-start gap-2.5 cursor-pointer group">
                    <input
                      type="checkbox"
                      checked={active}
                      onChange={() => toggleTag(tag)}
                      className="mt-0.5 accent-brand-500"
                    />
                    <div>
                      <span className={`text-xs font-medium ${active ? info.color.split(" ")[0] : "text-slate-400"}`}>
                        {info.label}
                      </span>
                      <p className="text-[10px] text-slate-500">{info.desc}</p>
                    </div>
                  </label>
                );
              })}
            </div>
          </div>

          {/* Allowlists (only shown if restricted tag active) */}
          {tags.includes("restricted") && (
            <div className="space-y-3 border-t border-slate-700/50 pt-3">
              <p className="text-xs font-medium text-amber-400">Acceso restringido</p>
              <div>
                <label className="text-[10px] text-slate-500 block mb-1">Peers permitidos (coma separado)</label>
                <input
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-2 py-1.5 text-xs text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-brand-500"
                  placeholder="peer-a, sensor-01"
                  value={allowedPeers}
                  onChange={(e) => setAllowedPeers(e.target.value)}
                />
              </div>
              <div>
                <label className="text-[10px] text-slate-500 block mb-1">Grupos permitidos (coma separado)</label>
                <input
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-2 py-1.5 text-xs text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-brand-500"
                  placeholder="hq, field"
                  value={allowedGroups}
                  onChange={(e) => setAllowedGroups(e.target.value)}
                />
              </div>
            </div>
          )}

          {/* Gateway hint */}
          {tags.includes("gateway") && (
            <div className="border-t border-slate-700/50 pt-3">
              <p className="text-xs font-medium text-violet-400 mb-1">Modo Gateway</p>
              <p className="text-[10px] text-slate-500">
                Configurá las rutas estáticas en el agente relay con la variable de entorno{" "}
                <code className="text-slate-300">RELAY_STATIC_ROUTES</code>:
              </p>
              <pre className="mt-2 bg-slate-950 border border-slate-800 rounded-lg p-2 text-[9px] font-mono text-violet-300 overflow-x-auto">
                {`RELAY_STATIC_ROUTES='{"satellite-sta-1": {"host": "10.5.0.2", "port": 9001}}'`}
              </pre>
            </div>
          )}

          {error && (
            <p className="text-xs text-red-400 bg-red-950/40 border border-red-900 rounded-lg px-3 py-2">
              {error}
            </p>
          )}

          <div className="flex items-center justify-end gap-3">
            {saved && <span className="text-xs text-emerald-400">Guardado</span>}
            <button
              onClick={save}
              disabled={saving}
              className="text-xs bg-brand-600 hover:bg-brand-700 disabled:opacity-40 text-white rounded-lg px-4 py-1.5 transition-colors"
            >
              {saving ? "Guardando…" : "Guardar"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function RelaysTab() {
  const [peers, setPeers] = useState<PeerInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    serverApi
      .listPeers()
      .then((ps) => setPeers(ps.sort((a, b) => a.peer_id.localeCompare(b.peer_id))))
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  if (loading) return <p className="text-xs text-slate-500 animate-pulse">Cargando peers…</p>;
  if (error) return <p className="text-xs text-red-400">{error}</p>;

  const relayPeers = peers.filter((p) => p.relay_capable);
  const nonRelayPeers = peers.filter((p) => !p.relay_capable);

  return (
    <div className="space-y-5">
      <div className="space-y-1">
        <p className="text-xs text-slate-500">
          Configura qué peers actúan como relay, sus tags de comportamiento y sus restricciones de acceso.
        </p>
        <div className="flex gap-3 text-[10px] text-slate-500">
          <span><span className="text-brand-400">Efímero:</span> buffer RAM, sin disco</span>
          <span><span className="text-amber-400">Restringido:</span> allowlist de peers/grupos</span>
          <span><span className="text-violet-400">Gateway:</span> rutas estáticas sin servidor</span>
        </div>
      </div>

      {relayPeers.length > 0 && (
        <div className="space-y-2">
          <p className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">
            Relays activos ({relayPeers.length})
          </p>
          {relayPeers.map((p) => (
            <RelayPeerRow key={p.peer_id} peer={p} onSaved={load} />
          ))}
        </div>
      )}

      {nonRelayPeers.length > 0 && (
        <div className="space-y-2">
          <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">
            Otros peers — habilitar como relay
          </p>
          {nonRelayPeers.map((p) => (
            <RelayPeerRow key={p.peer_id} peer={p} onSaved={load} />
          ))}
        </div>
      )}

      {peers.length === 0 && (
        <p className="text-xs text-slate-600 italic">Sin peers registrados.</p>
      )}
    </div>
  );
}

// ── Chart helpers ─────────────────────────────────────────────────────────────

function parsePrometheus(text: string): Record<string, number> {
  const out: Record<string, number> = {};
  for (const line of text.split("\n")) {
    if (line.startsWith("#") || !line.trim()) continue;
    const m = line.match(/^([a-zA-Z_][a-zA-Z0-9_:]*)(?:\{[^}]*\})?\s+([\d.e+\-]+)/);
    if (m) {
      const key = m[1].replace(/_total$/, "");
      if (!(key in out)) out[key] = parseFloat(m[2]);
    }
  }
  return out;
}

const QUALITY_COLOR: Record<string, string> = {
  excellent: "text-emerald-400",
  good:      "text-green-400",
  fair:      "text-yellow-400",
  poor:      "text-orange-400",
  critical:  "text-red-400",
  unknown:   "text-slate-500",
};

function qualityOf(rtt: number, jitter: number, loss: number): string {
  if (loss <= 0.01 && rtt <= 50  && jitter <= 5)   return "excellent";
  if (loss <= 0.05 && rtt <= 150 && jitter <= 20)  return "good";
  if (loss <= 0.15 && rtt <= 500 && jitter <= 80)  return "fair";
  if (loss <= 0.30 && rtt <= 1000)                 return "poor";
  return "critical";
}

interface MiniLineChartProps {
  values: number[];
  label: string;
  unit: string;
  color?: string;
  formatVal?: (v: number) => string;
}

function MiniLineChart({ values, label, unit, color = "#818cf8", formatVal }: MiniLineChartProps) {
  if (values.length === 0) return null;
  const W = 200, H = 52, PAD = 6;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const pts = values
    .map((v, i) => {
      const x = PAD + (i / Math.max(values.length - 1, 1)) * (W - PAD * 2);
      const y = H - PAD - ((v - min) / range) * (H - PAD * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const fmt = formatVal ?? ((v: number) => v.toFixed(1));

  return (
    <div className="space-y-0.5">
      <div className="flex justify-between text-[10px] text-slate-500">
        <span>{label}</span>
        <span className="font-mono">{fmt(values[values.length - 1])} {unit}</span>
      </div>
      <svg width={W} height={H} className="overflow-visible block">
        <defs>
          <linearGradient id={`grad-${label.replace(/\s/g, "")}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.15" />
            <stop offset="100%" stopColor={color} stopOpacity="0" />
          </linearGradient>
        </defs>
        {/* Area fill */}
        {values.length > 1 && (
          <polygon
            points={`${pts} ${(PAD + (values.length - 1) / Math.max(values.length - 1, 1) * (W - PAD * 2)).toFixed(1)},${H - PAD} ${PAD},${H - PAD}`}
            fill={`url(#grad-${label.replace(/\s/g, "")})`}
          />
        )}
        {/* Line */}
        <polyline
          points={pts}
          fill="none"
          stroke={color}
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        {/* Last point dot */}
        {values.length > 0 && (() => {
          const i = values.length - 1;
          const x = PAD + (i / Math.max(values.length - 1, 1)) * (W - PAD * 2);
          const y = H - PAD - ((values[i] - min) / range) * (H - PAD * 2);
          return <circle cx={x} cy={y} r="2.5" fill={color} />;
        })()}
        {/* Min/max labels */}
        <text x={PAD} y={H - PAD - ((max - min) / range) * (H - PAD * 2) - 3} fontSize="8" fill="#64748b" textAnchor="start">{fmt(max)}</text>
        <text x={PAD} y={H - PAD + 9} fontSize="8" fill="#64748b" textAnchor="start">{fmt(min)}</text>
      </svg>
    </div>
  );
}

interface OtelCardProps { label: string; value: string; sub?: string }

function OtelCard({ label, value, sub }: OtelCardProps) {
  return (
    <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl px-3 py-2.5 space-y-0.5">
      <p className="text-[10px] text-slate-500 uppercase tracking-wider font-medium">{label}</p>
      <p className="text-lg font-mono font-semibold text-slate-100 leading-none">{value}</p>
      {sub && <p className="text-[10px] text-slate-500">{sub}</p>}
    </div>
  );
}

// ── Network graph table ───────────────────────────────────────────────────────

function NetworkGraphTable() {
  const [edges, setEdges] = useState<NetworkEdge[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    serverApi
      .getNetworkGraph()
      .then((g) => setEdges(g.edges))
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
    const iv = setInterval(load, 30_000);
    return () => clearInterval(iv);
  }, [load]);

  if (loading) return <p className="text-xs text-slate-500 animate-pulse">Cargando grafo…</p>;
  if (error) return <p className="text-xs text-red-400">{error}</p>;
  if (edges.length === 0)
    return (
      <p className="text-xs text-slate-600 italic">
        Sin edges medidos aún — los links aparecen después de la primera transferencia entre peers.
      </p>
    );

  return (
    <div className="overflow-x-auto rounded-xl border border-slate-800">
      <table className="w-full text-[11px]">
        <thead>
          <tr className="text-left text-slate-500 bg-slate-800/50">
            <th className="px-3 py-2 font-medium">Origen</th>
            <th className="px-3 py-2 font-medium">Destino</th>
            <th className="px-3 py-2 font-medium text-right">RTT (ms)</th>
            <th className="px-3 py-2 font-medium text-right">Jitter (ms)</th>
            <th className="px-3 py-2 font-medium text-right">Loss</th>
            <th className="px-3 py-2 font-medium">Calidad</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800">
          {edges.map((e, i) => {
            const q = qualityOf(e.rtt_ms, e.jitter_ms, e.loss_rate);
            return (
              <tr key={i} className="hover:bg-slate-800/30 transition-colors">
                <td className="px-3 py-2 font-mono text-slate-300">{e.source}</td>
                <td className="px-3 py-2 font-mono text-slate-300">{e.target}</td>
                <td className="px-3 py-2 text-right font-mono text-slate-200">{e.rtt_ms?.toFixed(1) ?? "—"}</td>
                <td className="px-3 py-2 text-right font-mono text-slate-200">{e.jitter_ms?.toFixed(1) ?? "—"}</td>
                <td className="px-3 py-2 text-right font-mono text-slate-200">
                  {e.loss_rate != null ? `${(e.loss_rate * 100).toFixed(1)}%` : "—"}
                </td>
                <td className={`px-3 py-2 font-medium capitalize ${QUALITY_COLOR[q]}`}>{q}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ── Metrics tab ──────────────────────────────────────────────────────────────

type MetricsView = "peer" | "graph";

function MetricsTab() {
  const [view, setView] = useState<MetricsView>("peer");
  const [peers, setPeers] = useState<PeerInfo[]>([]);
  const [selectedPeer, setSelectedPeer] = useState<string | null>(null);
  const [history, setHistory] = useState<MetricHistory | null>(null);
  const [otelRaw, setOtelRaw] = useState<string | null>(null);
  const [otelParsed, setOtelParsed] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    serverApi
      .listPeers()
      .then((ps) => setPeers(ps.sort((a, b) => a.peer_id.localeCompare(b.peer_id))))
      .catch((e) => setError(`Error cargando peers: ${(e as Error).message}`));
  }, []);

  const fetchPeerData = useCallback(
    (peerId: string) => {
      setLoading(true);
      setError(null);
      Promise.all([
        serverApi.getMetricHistory(peerId),
        serverApi.getPeerMetrics(peerId).catch(() => ({ raw: "" })),
      ])
        .then(([hist, otel]) => {
          setHistory(hist);
          const raw = (otel as { raw: string }).raw ?? "";
          setOtelRaw(raw);
          setOtelParsed(parsePrometheus(raw));
        })
        .catch((e) => setError((e as Error).message))
        .finally(() => setLoading(false));
    },
    [],
  );

  useEffect(() => {
    if (intervalRef.current) clearInterval(intervalRef.current);
    if (!selectedPeer) {
      setHistory(null);
      setOtelRaw(null);
      setOtelParsed({});
      return;
    }
    fetchPeerData(selectedPeer);
    intervalRef.current = setInterval(() => fetchPeerData(selectedPeer), 15_000);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [selectedPeer, fetchPeerData]);

  const samples = history?.samples ?? [];
  const rtts    = samples.map((s) => s.rtt_ms);
  const jitters = samples.map((s) => s.jitter_ms);
  const losses  = samples.map((s) => s.loss_rate * 100);

  const totalTransfers  = otelParsed["rs_transfers"] ?? otelParsed["rs_transfers_total"] ?? null;
  const packetsSent     = otelParsed["rs_packets_sent"] ?? otelParsed["rs_packets_sent_total"] ?? null;
  const packetsRecov    = otelParsed["rs_packets_recovered"] ?? otelParsed["rs_packets_recovered_total"] ?? null;
  const recoveryRate    = packetsRecov != null && packetsSent != null && packetsSent > 0
    ? ((packetsRecov / packetsSent) * 100).toFixed(1) + "%"
    : null;

  const lastSample = samples.length > 0 ? samples[samples.length - 1] : null;
  const currentQuality = lastSample
    ? qualityOf(lastSample.rtt_ms, lastSample.jitter_ms, lastSample.loss_rate)
    : null;

  return (
    <div className="space-y-4">
      {/* Sub-view toggle */}
      <div className="flex gap-1 bg-slate-800/50 rounded-lg p-0.5 w-fit">
        {(["peer", "graph"] as MetricsView[]).map((v) => (
          <button
            key={v}
            onClick={() => setView(v)}
            className={`px-3 py-1.5 text-xs rounded-md transition-colors font-medium ${
              view === v
                ? "bg-slate-700 text-slate-100"
                : "text-slate-500 hover:text-slate-300"
            }`}
          >
            {v === "peer" ? "Por peer" : "Red P2P"}
          </button>
        ))}
      </div>

      {view === "graph" && <NetworkGraphTable />}

      {view === "peer" && (
        <>
          {/* Peer selector */}
          <div className="flex flex-col gap-1.5">
            <label className="text-xs text-slate-500 font-medium">Peer</label>
            <select
              className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-brand-500 appearance-none"
              value={selectedPeer ?? ""}
              onChange={(e) => setSelectedPeer(e.target.value || null)}
            >
              <option value="">— Seleccionar peer —</option>
              {peers.map((p) => (
                <option key={p.peer_id} value={p.peer_id}>
                  {p.peer_id} [{p.group}] {p.online ? "●" : "○"}
                </option>
              ))}
            </select>
          </div>

          {loading && (
            <p className="text-xs text-slate-500 animate-pulse">Consultando…</p>
          )}

          {error && (
            <p className="text-xs text-red-400 bg-red-950/40 border border-red-900 rounded-lg px-3 py-2">
              {error}
            </p>
          )}

          {!selectedPeer && !error && (
            <div className="py-10 flex flex-col items-center justify-center border-2 border-dashed border-slate-800/50 rounded-2xl">
              <p className="text-xs text-slate-500">Seleccioná un peer para ver su telemetría</p>
            </div>
          )}

          {selectedPeer && !loading && (
            <div className="space-y-5">
              {/* Quality + refresh */}
              <div className="flex items-center justify-between">
                {currentQuality && (
                  <span className={`text-xs font-medium capitalize ${QUALITY_COLOR[currentQuality]}`}>
                    {currentQuality} · {samples.length} sample{samples.length !== 1 ? "s" : ""}
                  </span>
                )}
                <button
                  onClick={() => selectedPeer && fetchPeerData(selectedPeer)}
                  className="text-[10px] text-brand-400 hover:text-brand-300 font-medium uppercase tracking-wider"
                >
                  Actualizar
                </button>
              </div>

              {/* OTel counter cards */}
              {(totalTransfers != null || packetsSent != null || packetsRecov != null) && (
                <div>
                  <p className="text-[10px] text-slate-500 font-medium uppercase tracking-wider mb-2">
                    Contadores OTel
                  </p>
                  <div className="grid grid-cols-2 gap-2">
                    {totalTransfers != null && (
                      <OtelCard label="Transfers" value={String(totalTransfers)} sub="total enviados" />
                    )}
                    {packetsSent != null && (
                      <OtelCard label="Paquetes RS" value={String(packetsSent)} sub="enviados" />
                    )}
                    {packetsRecov != null && (
                      <OtelCard label="Recuperados FEC" value={String(packetsRecov)} sub="vía RS" />
                    )}
                    {recoveryRate && (
                      <OtelCard label="Recovery Rate" value={recoveryRate} sub="paquetes/total" />
                    )}
                  </div>
                </div>
              )}

              {/* RTT / Jitter / Loss charts */}
              {samples.length > 0 && (
                <div>
                  <p className="text-[10px] text-slate-500 font-medium uppercase tracking-wider mb-2">
                    Historial de red ({samples.length} muestras)
                  </p>
                  <div className="grid grid-cols-1 gap-4 bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
                    <MiniLineChart
                      values={rtts}
                      label="RTT"
                      unit="ms"
                      color="#818cf8"
                      formatVal={(v) => v.toFixed(0)}
                    />
                    <MiniLineChart
                      values={jitters}
                      label="Jitter"
                      unit="ms"
                      color="#34d399"
                      formatVal={(v) => v.toFixed(1)}
                    />
                    <MiniLineChart
                      values={losses}
                      label="Loss rate"
                      unit="%"
                      color="#f59e0b"
                      formatVal={(v) => v.toFixed(1)}
                    />
                  </div>
                </div>
              )}

              {samples.length === 0 && !loading && (
                <p className="text-xs text-slate-600 italic">
                  Sin historial de red aún — el agente reporta después de cada transferencia.
                </p>
              )}

              {/* Raw OTel (collapsible) */}
              {otelRaw && (
                <details className="group">
                  <summary className="text-[10px] text-slate-600 cursor-pointer hover:text-slate-400 select-none">
                    Ver Prometheus raw
                  </summary>
                  <div className="mt-2 bg-slate-950 border border-slate-800 rounded-xl overflow-hidden">
                    <pre className="p-3 text-[9px] font-mono text-slate-500 overflow-auto max-h-48 leading-relaxed">
                      {otelRaw}
                    </pre>
                  </div>
                </details>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ── Policies tab ─────────────────────────────────────────────────────────────

const POLICY_LABELS: Record<string, { label: string; desc: string; color: string }> = {
  allow_all:  { label: "Permitir todo",    desc: "Acepta transferencias de cualquier peer",           color: "text-emerald-400" },
  deny_all:   { label: "Bloquear todo",    desc: "Rechaza todas las transferencias entrantes",         color: "text-red-400" },
  allow_list: { label: "Lista de acceso",  desc: "Solo acepta de peers en la lista explícita",        color: "text-amber-400" },
};

interface PolicyPeerRowProps {
  peer: PeerInfo;
  onSaved: () => void;
}

function PolicyPeerRow({ peer, onSaved }: PolicyPeerRowProps) {
  const [expanded, setExpanded] = useState(false);
  const [policy, setPolicy] = useState<IncomingPolicyConfig["incoming_policy"]>(
    (peer.incoming_policy as IncomingPolicyConfig["incoming_policy"]) ?? "allow_all"
  );
  const [allowedPeers, setAllowedPeers] = useState(
    (peer.incoming_allowed_peers ?? []).join(", ")
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const cfg: IncomingPolicyConfig = {
        incoming_policy: policy,
        incoming_allowed_peers: policy === "allow_list"
          ? allowedPeers.split(",").map((s) => s.trim()).filter(Boolean)
          : [],
      };
      await serverApi.updateIncomingPolicy(peer.peer_id, cfg);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
      onSaved();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  const policyInfo = POLICY_LABELS[policy] ?? POLICY_LABELS.allow_all;

  return (
    <div className="border border-slate-700/60 rounded-xl overflow-hidden">
      <div
        className="flex items-center gap-3 px-4 py-3 bg-slate-800/30 cursor-pointer hover:bg-slate-800/50 transition-colors"
        onClick={() => setExpanded((v) => !v)}
      >
        <div className="flex-1 min-w-0 flex items-center gap-2">
          <span className="text-xs font-mono text-slate-200 truncate">{peer.peer_id}</span>
          {peer.owner && peer.owner !== peer.peer_id && (
            <span className="text-[10px] text-slate-500">[{peer.owner}]</span>
          )}
          <span className={`text-[9px] px-1 rounded ${peer.online ? "text-emerald-400" : "text-slate-600"}`}>
            {peer.online ? "● online" : "○ offline"}
          </span>
        </div>
        <span className={`text-[10px] shrink-0 ${policyInfo.color}`}>{policyInfo.label}</span>
        <svg
          className={`w-3.5 h-3.5 text-slate-500 transition-transform shrink-0 ${expanded ? "rotate-180" : ""}`}
          viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
        >
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </div>

      {expanded && (
        <div className="px-4 py-4 border-t border-slate-700/60 space-y-4 bg-slate-900/20">
          <div>
            <p className="text-xs font-medium text-slate-300 mb-2">Política de transferencias entrantes</p>
            <div className="space-y-2">
              {(Object.entries(POLICY_LABELS) as [IncomingPolicyConfig["incoming_policy"], typeof POLICY_LABELS[string]][]).map(([val, info]) => (
                <label key={val} className="flex items-start gap-2.5 cursor-pointer">
                  <input
                    type="radio"
                    name={`policy-${peer.peer_id}`}
                    value={val}
                    checked={policy === val}
                    onChange={() => setPolicy(val)}
                    className="mt-0.5 accent-brand-500"
                  />
                  <div>
                    <span className={`text-xs font-medium ${info.color}`}>{info.label}</span>
                    <p className="text-[10px] text-slate-500">{info.desc}</p>
                  </div>
                </label>
              ))}
            </div>
          </div>

          {policy === "allow_list" && (
            <div>
              <label className="text-[10px] text-slate-500 block mb-1">
                Peers permitidos (coma separado)
              </label>
              <input
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-2 py-1.5 text-xs text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-brand-500"
                placeholder="peer-a, edge-sensor-01"
                value={allowedPeers}
                onChange={(e) => setAllowedPeers(e.target.value)}
              />
            </div>
          )}

          {error && (
            <p className="text-xs text-red-400 bg-red-950/40 border border-red-900 rounded-lg px-3 py-2">
              {error}
            </p>
          )}

          <div className="flex items-center justify-end gap-3">
            {saved && <span className="text-xs text-emerald-400">Guardado</span>}
            <button
              onClick={save}
              disabled={saving}
              className="text-xs bg-brand-600 hover:bg-brand-700 disabled:opacity-40 text-white rounded-lg px-4 py-1.5 transition-colors"
            >
              {saving ? "Guardando…" : "Guardar"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function PoliciesTab() {
  const [peers, setPeers] = useState<PeerInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    serverApi
      .listPeers()
      .then((ps) => setPeers(ps.sort((a, b) => a.peer_id.localeCompare(b.peer_id))))
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  if (loading) return <p className="text-xs text-slate-500 animate-pulse">Cargando peers…</p>;
  if (error) return <p className="text-xs text-red-400">{error}</p>;
  if (peers.length === 0)
    return <p className="text-xs text-slate-600 italic">Sin peers registrados.</p>;

  return (
    <div className="space-y-4">
      <p className="text-xs text-slate-500">
        Controlá qué peers pueden recibir transferencias entrantes. Útil para agentes headless y
        dispositivos que deben quedar en modo solo-envío o con whitelist de fuentes confiables.
        El agente aplica la política al arrancar — cambiarla aquí requiere reinicio del agente.
      </p>
      <div className="space-y-2">
        {peers.map((p) => (
          <PolicyPeerRow key={p.peer_id} peer={p} onSaved={load} />
        ))}
      </div>
    </div>
  );
}

// ── Main panel ────────────────────────────────────────────────────────────────

const TAB_LABELS: Record<Tab, string> = {
  "scopes": "Visibilidad",
  "invites": "Invites",
  "device-tokens": "Device Tokens",
  "relays": "Relays",
  "metrics": "Network Health",
  "policies": "Políticas",
};

export default function AdminPanel(_props: Props) {
  const [tab, setTab] = useState<Tab>("metrics");

  return (
    <div className="flex flex-col h-full">
      {/* Page header */}
      <div className="px-5 py-4 border-b border-slate-800 flex-shrink-0">
        <h2 className="text-sm font-semibold text-slate-200">Administración</h2>
        <p className="text-xs text-slate-500 mt-0.5">Gestión de accesos, grupos y tokens del servidor</p>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-slate-800 overflow-x-auto flex-shrink-0">
        {(Object.keys(TAB_LABELS) as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-5 py-3 text-xs font-medium transition-colors border-b-2 -mb-px whitespace-nowrap ${
              tab === t
                ? "border-brand-500 text-brand-400"
                : "border-transparent text-slate-500 hover:text-slate-300"
            }`}
          >
            {TAB_LABELS[t]}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto px-5 py-5 max-w-2xl">
        {tab === "scopes" && <ScopesTab />}
        {tab === "invites" && <InvitesTab />}
        {tab === "device-tokens" && <DeviceTokensTab />}
        {tab === "relays" && <RelaysTab />}
        {tab === "metrics" && <MetricsTab />}
        {tab === "policies" && <PoliciesTab />}
      </div>
    </div>
  );
}
