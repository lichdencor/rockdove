import { useEffect, useRef, useState } from "react";
import type { FileMetadata, PeerInfo, RecommendationResponse, TransferResult } from "../types";
import { agentApi, serverApi } from "../api";
import TransferAnimation from "./TransferAnimation";

interface Props {
  peer: PeerInfo;
  preselectedFile?: FileMetadata;
  serverUrl: string;
  peerId: string;
  onComplete: (result: TransferResult) => void;
  onClose: () => void;
}

const QUALITY_COLORS: Record<string, string> = {
  excellent: "text-emerald-400 bg-emerald-950/50 border-emerald-800",
  good: "text-green-400 bg-green-950/50 border-green-800",
  fair: "text-yellow-400 bg-yellow-950/50 border-yellow-800",
  poor: "text-orange-400 bg-orange-950/50 border-orange-800",
  critical: "text-red-400 bg-red-950/50 border-red-800",
  unknown: "text-slate-400 bg-slate-800/50 border-slate-700",
};

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}

function rsOverhead(r: number): string {
  return `+${Math.round((r / (1 - r)) * 100)}%`;
}

export default function TransferDialog({ peer, preselectedFile, serverUrl, peerId, onComplete, onClose }: Props) {
  const [files, setFiles] = useState<FileMetadata[]>([]);
  const [selectedFile, setSelectedFile] = useState<FileMetadata | null>(preselectedFile ?? null);
  const [recommendation, setRecommendation] = useState<RecommendationResponse | null>(null);
  const [adaptive, setAdaptive] = useState(true);
  const [redundancy, setRedundancy] = useState(0.25);
  const [userOverride, setUserOverride] = useState(false);
  const [transport, setTransport] = useState<"udp" | "quic">(peer.transport ?? "udp");
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<TransferResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [requestingTransport, setRequestingTransport] = useState(false);
  const [transportRequestSent, setTransportRequestSent] = useState(false);
  const [transportRequestError, setTransportRequestError] = useState<string | null>(null);
  const overlayRef = useRef<HTMLDivElement>(null);

  // Load files
  useEffect(() => {
    agentApi.listFiles().then(setFiles).catch(() => {});
  }, []);

  // Fetch recommendation from server
  useEffect(() => {
    serverApi
      .getRecommendation(peerId)
      .then((rec) => {
        setRecommendation(rec);
        if (!userOverride) setRedundancy(rec.redundancy_level);
      })
      .catch(() => {});
  }, [peerId, serverUrl]);

  async function handleSend() {
    if (!selectedFile) return;
    setSending(true);
    setError(null);
    try {
      // adaptive=true → null means "let the server decide" (agent uses its own recommendation call)
      const level = adaptive ? undefined : redundancy;
      const res = await agentApi.sendFile(selectedFile.file_id, peer.peer_id, level, transport);
      setResult(res);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSending(false);
    }
  }

  function handleSliderChange(val: number) {
    setRedundancy(val);
    setUserOverride(true);
  }

  function handleResetRecommendation() {
    if (recommendation) {
      setRedundancy(recommendation.redundancy_level);
      setUserOverride(false);
    }
  }

  async function handleRequestTransport() {
    setRequestingTransport(true);
    setTransportRequestError(null);
    try {
      await agentApi.requestTransport(peer.peer_id, transport);
      setTransportRequestSent(true);
    } catch (e) {
      setTransportRequestError((e as Error).message);
    } finally {
      setRequestingTransport(false);
    }
  }

  function handleOverlayClick(e: React.MouseEvent) {
    if (e.target === overlayRef.current && !sending) onClose();
  }

  const qualityClass = recommendation
    ? QUALITY_COLORS[recommendation.quality] ?? QUALITY_COLORS.unknown
    : QUALITY_COLORS.unknown;

  return (
    <div
      ref={overlayRef}
      onClick={handleOverlayClick}
      className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-50"
    >
      <div className={`bird-panel rounded-2xl shadow-2xl w-full overflow-visible ${sending ? "max-w-2xl" : "max-w-md"}`}>
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800">
          <div>
            <h2 className="font-medium text-slate-200">Enviar archivo</h2>
            <p className="text-xs text-slate-500 mt-0.5 font-mono">→ {peer.peer_id}</p>
          </div>
          {!sending && (
            <button onClick={onClose} className="text-slate-500 hover:text-slate-300 text-lg leading-none">×</button>
          )}
        </div>

        <div className="px-6 py-5 space-y-5">
          {sending ? (
            <TransferAnimation targetPeer={peer.peer_id} />
          ) : result ? (
            /* ── Result ── */
            <div className="text-center py-4">
              <div className="text-4xl mb-3">
                {result.status === "ok" ? "✅" : result.status === "degraded" ? "⚠️" : "❌"}
              </div>
              <p className={`text-lg font-semibold ${result.status === "ok" ? "text-emerald-400" : result.status === "degraded" ? "text-yellow-400" : "text-red-400"}`}>
                {result.status}
              </p>
              {result.status === "degraded" && (
                <>
                  <p className="text-xs text-slate-400 mt-1">
                    RS recuperó {result.recovered_blocks}/{result.total_blocks} bloques
                  </p>
                  <div className="mt-3 flex items-start gap-2 bg-yellow-950/30 border border-yellow-800/50 rounded-lg px-3 py-2.5 text-xs text-yellow-300 text-left">
                    <span className="flex-shrink-0">⚠️</span>
                    <span>
                      Fue exitoso — RS recuperó {result.recovered_blocks}/{result.total_blocks} bloques
                    </span>
                  </div>
                </>
              )}
              {result.reason && (
                <p className="text-xs text-slate-500 mt-1">{result.reason}</p>
              )}
              <button
                onClick={() => onComplete(result)}
                className="bird-btn mt-5 bg-brand-600 hover:bg-brand-700 text-white rounded-lg px-6 py-2 text-sm transition-colors"
              >
                Cerrar
              </button>
            </div>
          ) : (
            <>
              {/* ── File selector ── */}
              <div>
                <label className="block text-xs text-slate-400 mb-2">Archivo</label>
                {files.length === 0 ? (
                  <p className="text-xs text-slate-500">No hay archivos locales. Subí uno primero.</p>
                ) : (
                  <select
                    value={selectedFile?.file_id ?? ""}
                    onChange={(e) => setSelectedFile(files.find((f) => f.file_id === e.target.value) ?? null)}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2.5 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-brand-500"
                  >
                    <option value="">Seleccioná un archivo</option>
                    {files.map((f) => (
                      <option key={f.file_id} value={f.file_id}>
                        {f.filename} ({formatBytes(f.size)})
                      </option>
                    ))}
                  </select>
                )}
              </div>

              {/* ── Transport ── */}
              <div>
                <label className="block text-xs text-slate-400 mb-2">Transport</label>
                <div className="flex gap-2">
                  {(["udp", "quic"] as const).map((t) => {
                    const peerTransport = peer.transport ?? "udp";
                    const isRegistered = peerTransport === t;
                    const isSelected = transport === t;
                    return (
                      <button
                        key={t}
                        type="button"
                        onClick={() => {
                          setTransport(t);
                          setTransportRequestSent(false);
                          setTransportRequestError(null);
                        }}
                        className={`flex-1 py-2 text-xs font-mono rounded-lg border transition-colors cursor-pointer ${
                          isSelected
                            ? t === "quic"
                              ? "bg-violet-900/60 border-violet-700 text-violet-300"
                              : "bg-slate-700 border-slate-600 text-slate-200"
                            : "bg-slate-800/40 border-slate-700/50 text-slate-500 hover:text-slate-300 hover:border-slate-600"
                        }`}
                      >
                        {t.toUpperCase()}
                        {isRegistered ? (
                          <span className="ml-1 text-slate-500 font-sans normal-case">✓</span>
                        ) : null}
                      </button>
                    );
                  })}
                </div>

                {/* Mismatch warning */}
                {transport !== (peer.transport ?? "udp") ? (
                  <div className="mt-2 bg-amber-950/30 border border-amber-800/50 rounded-lg px-3 py-2 text-xs text-amber-400 space-y-2">
                    <div className="flex items-start gap-2">
                      <svg className="w-3.5 h-3.5 flex-shrink-0 mt-px" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
                        <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
                      </svg>
                      {transportRequestSent ? (
                        <span className="text-amber-300">
                          Solicitud enviada — esperá que el peer acepte.
                        </span>
                      ) : (
                        <span>
                          El peer está registrado como <span className="font-mono">{(peer.transport ?? "udp").toUpperCase()}</span>.
                          Para usar {transport.toUpperCase()}, el agente remoto debe iniciarse con{" "}
                          <code className="text-amber-300">TRANSPORT_MODE={transport}</code>.
                        </span>
                      )}
                    </div>
                    {transportRequestError ? (
                      <p className="text-red-400">{transportRequestError}</p>
                    ) : null}
                    {!transportRequestSent ? (
                      <button
                        type="button"
                        onClick={handleRequestTransport}
                        disabled={requestingTransport}
                        className="bg-amber-800/60 hover:bg-amber-700/60 disabled:opacity-40 text-amber-200 border border-amber-700/50 rounded-lg px-3 py-1.5 text-xs transition-colors"
                      >
                        {requestingTransport ? "Enviando…" : "Solicitar cambio"}
                      </button>
                    ) : null}
                  </div>
                ) : null}

                {/* QUIC info when selected and no mismatch */}
                {transport === "quic" && transport === (peer.transport ?? "udp") ? (
                  <div className="mt-2 flex items-start gap-2 bg-violet-950/30 border border-violet-800/50 rounded-lg px-3 py-2.5 text-xs text-violet-300">
                    <svg className="w-3.5 h-3.5 flex-shrink-0 mt-px" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
                    </svg>
                    <div>
                      <p className="font-medium mb-0.5">Negociación QUIC/TLS</p>
                      <p className="text-violet-400/80">
                        El receptor deberá aprobar tu certificado antes de que los datos se transfieran.
                        Asegurate de que el peer tenga la app abierta.
                      </p>
                    </div>
                  </div>
                ) : null}
              </div>

              {/* ── Redundancy ── */}
              <div>
                {/* Recommendation chip + adaptive toggle */}
                {recommendation && (
                  <div className={`flex items-center justify-between rounded-lg border px-3 py-2 mb-3 text-xs ${qualityClass}`}>
                    <span>
                      <span className="font-medium">{recommendation.quality}</span>
                      {recommendation.profile_name && (
                        <span className="ml-1.5 opacity-70">· {recommendation.profile_name}</span>
                      )}
                      {recommendation.based_on_samples > 0
                        ? ` · ${recommendation.based_on_samples} muestra${recommendation.based_on_samples !== 1 ? "s" : ""}`
                        : " · sin muestras aún"}
                    </span>
                    <span className="opacity-70">
                      {Math.round(recommendation.redundancy_level * 100)}%
                    </span>
                  </div>
                )}

                {/* Adaptive toggle */}
                <div className="flex items-center justify-between mb-3">
                  <div>
                    <span className="text-xs text-slate-400">Redundancia adaptativa</span>
                    <span className="ml-2 text-xs text-slate-600">
                      {adaptive ? "usa la recomendación del servidor" : "manual"}
                    </span>
                  </div>
                  <button
                    onClick={() => setAdaptive((v) => !v)}
                    className={`relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors ${
                      adaptive ? "bg-brand-600" : "bg-slate-700"
                    }`}
                  >
                    <span
                      className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
                        adaptive ? "translate-x-4" : "translate-x-0"
                      }`}
                    />
                  </button>
                </div>

                {/* Manual slider — only shown when adaptive is off */}
                {!adaptive && (
                  <>
                    <div className="flex items-center justify-between mb-2">
                      <label className="text-xs text-slate-400">Nivel de redundancia RS</label>
                      <span className="text-xs font-mono text-slate-300">{Math.round(redundancy * 100)}%</span>
                    </div>
                    {userOverride && recommendation && (
                      <div className="flex justify-end mb-2">
                        <button
                          onClick={handleResetRecommendation}
                          className="text-xs text-slate-500 underline hover:text-slate-300"
                        >
                          restablecer sugerido ({Math.round(recommendation.redundancy_level * 100)}%)
                        </button>
                      </div>
                    )}
                    <input
                      type="range"
                      min={5} max={50} step={1}
                      value={Math.round(redundancy * 100)}
                      onChange={(e) => handleSliderChange(Number(e.target.value) / 100)}
                      className="w-full accent-brand-500"
                    />
                    <div className="flex justify-between text-xs text-slate-600 mt-1">
                      <span>5% — mínimo</span>
                      <span className="text-slate-500">overhead: {rsOverhead(redundancy)} · tolera {Math.round(redundancy * 100)}% pérdida</span>
                      <span>50% — máximo</span>
                    </div>
                  </>
                )}
              </div>

              {/* Error */}
              {error && (
                <p className="text-xs text-red-400 bg-red-950/40 border border-red-900 rounded-lg px-3 py-2">
                  {error}
                </p>
              )}

              {/* Actions */}
              <div className="flex gap-3 pt-1">
                <button
                  onClick={onClose}
                  disabled={sending}
                  className="flex-1 bg-slate-800 hover:bg-slate-700 disabled:opacity-40 text-slate-300 rounded-lg py-2.5 text-sm transition-colors"
                >
                  Cancelar
                </button>
                <button
                  onClick={handleSend}
                  disabled={sending || !selectedFile}
                  className="bird-btn flex-1 bg-brand-600 hover:bg-brand-700 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded-lg py-2.5 text-sm font-medium transition-colors"
                >
                  Enviar
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
