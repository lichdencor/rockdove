import { useEffect, useState } from "react";
import type { IncomingConnection } from "../types";
import { agentApi } from "../api";

function timeAgo(iso: string): string {
  const diffS = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (diffS < 60) return `hace ${diffS}s`;
  return `hace ${Math.floor(diffS / 60)}m`;
}

export default function IncomingConnectionsBanner() {
  const [conns, setConns] = useState<IncomingConnection[]>([]);
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  useEffect(() => {
    let active = true;

    async function poll() {
      try {
        const all = await agentApi.listIncoming();
        if (active) setConns(all.filter((c) => c.status === "pending"));
      } catch {}
    }

    poll();
    const id = setInterval(poll, 3000);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, []);

  async function handleAccept(tid: string) {
    setBusy((b) => ({ ...b, [tid]: true }));
    try {
      await agentApi.acceptIncoming(tid);
      setConns((prev) => prev.filter((c) => c.transfer_id !== tid));
    } catch {}
    finally { setBusy((b) => ({ ...b, [tid]: false })); }
  }

  async function handleReject(tid: string) {
    setBusy((b) => ({ ...b, [tid]: true }));
    try {
      await agentApi.rejectIncoming(tid);
      setConns((prev) => prev.filter((c) => c.transfer_id !== tid));
    } catch {}
    finally { setBusy((b) => ({ ...b, [tid]: false })); }
  }

  if (conns.length === 0) return null;

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-3 max-w-xs w-full">
      {conns.map((conn) => (
        <div
          key={conn.transfer_id}
          className="bg-slate-900 border border-violet-800/70 rounded-xl shadow-2xl overflow-hidden"
        >
          {/* Header */}
          <div className="flex items-center gap-2 px-4 py-3 bg-violet-950/40 border-b border-violet-800/40">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-violet-400 opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-violet-500" />
            </span>
            <span className="text-xs font-medium text-violet-200 flex-1">
              Conexión QUIC entrante
            </span>
            <span className="text-xs text-slate-500">{timeAgo(conn.arrived_at)}</span>
          </div>

          {/* Cert fields */}
          <div className="px-4 py-3 space-y-2">
            <Field label="Peer ID" value={conn.peer_id} mono violet />
            <Field label="Cert CN" value={conn.cert_cn} mono />
            <Field
              label="SHA-256"
              value={`${conn.cert_fingerprint.slice(0, 16)}…`}
              title={conn.cert_fingerprint}
              mono
            />

            {/* Expandable: full fingerprint */}
            <button
              onClick={() => setExpanded((e) => ({ ...e, [conn.transfer_id]: !e[conn.transfer_id] }))}
              className="text-xs text-slate-600 hover:text-slate-400 transition-colors"
            >
              {expanded[conn.transfer_id] ? "Ocultar fingerprint" : "Ver fingerprint completo"}
            </button>
            {expanded[conn.transfer_id] && (
              <p className="text-xs font-mono text-slate-500 break-all bg-slate-800/50 rounded px-2 py-1.5">
                {conn.cert_fingerprint}
              </p>
            )}
          </div>

          {/* Actions */}
          <div className="flex gap-2 px-4 pb-3">
            <button
              onClick={() => handleAccept(conn.transfer_id)}
              disabled={busy[conn.transfer_id]}
              className="flex-1 text-xs bg-violet-900/60 hover:bg-violet-800/60 text-violet-200 border border-violet-700/60 rounded-lg py-2 font-medium transition-colors disabled:opacity-40"
            >
              {busy[conn.transfer_id] ? "…" : "Aceptar"}
            </button>
            <button
              onClick={() => handleReject(conn.transfer_id)}
              disabled={busy[conn.transfer_id]}
              className="flex-1 text-xs bg-slate-800/60 hover:bg-slate-700/60 text-slate-400 border border-slate-700/60 rounded-lg py-2 transition-colors disabled:opacity-40"
            >
              Rechazar
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}

function Field({
  label,
  value,
  title,
  mono,
  violet,
}: {
  label: string;
  value: string;
  title?: string;
  mono?: boolean;
  violet?: boolean;
}) {
  return (
    <div className="flex items-start gap-2">
      <span className="text-xs text-slate-500 w-16 flex-shrink-0 pt-px">{label}</span>
      <span
        title={title}
        className={`text-xs truncate ${mono ? "font-mono" : ""} ${violet ? "text-violet-300" : "text-slate-300"}`}
      >
        {value}
      </span>
    </div>
  );
}
