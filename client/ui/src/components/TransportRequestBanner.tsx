import { useEffect, useState } from "react";
import type { TransportRequest } from "../types";
import { agentApi } from "../api";

const TRANSPORT_BADGE: Record<string, string> = {
  quic: "text-violet-400 bg-violet-950/50 border-violet-800",
  udp: "text-slate-500 bg-slate-800/50 border-slate-700",
};

function timeAgo(iso: string): string {
  const diffS = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (diffS < 60) return `hace ${diffS}s`;
  return `hace ${Math.floor(diffS / 60)}m`;
}

export default function TransportRequestBanner() {
  const [requests, setRequests] = useState<TransportRequest[]>([]);
  const [busy, setBusy] = useState<Record<string, boolean>>({});

  useEffect(() => {
    let active = true;

    async function poll() {
      try {
        const all = await agentApi.listTransportRequests();
        if (active) setRequests(all.filter((r) => r.status === "pending"));
      } catch {}
    }

    poll();
    const id = setInterval(poll, 3000);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, []);

  async function handleAccept(reqId: string) {
    setBusy((b) => ({ ...b, [reqId]: true }));
    try {
      await agentApi.acceptTransportRequest(reqId);
      setRequests((prev) => prev.filter((r) => r.request_id !== reqId));
    } catch {}
    finally { setBusy((b) => ({ ...b, [reqId]: false })); }
  }

  async function handleReject(reqId: string) {
    setBusy((b) => ({ ...b, [reqId]: true }));
    try {
      await agentApi.rejectTransportRequest(reqId);
      setRequests((prev) => prev.filter((r) => r.request_id !== reqId));
    } catch {}
    finally { setBusy((b) => ({ ...b, [reqId]: false })); }
  }

  if (requests.length === 0) return null;

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-3 max-w-xs w-full">
      {requests.map((req) => {
        const badgeCls =
          TRANSPORT_BADGE[req.requested_transport] ?? TRANSPORT_BADGE.udp;
        return (
          <div
            key={req.request_id}
            className="bg-slate-900 border border-violet-800/70 rounded-xl shadow-2xl overflow-hidden"
          >
            {/* Header */}
            <div className="flex items-center gap-2 px-4 py-3 bg-violet-950/40 border-b border-violet-800/40">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-violet-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-violet-500" />
              </span>
              <span className="text-xs font-medium text-violet-200 flex-1">
                Solicitud de transporte
              </span>
              <span className="text-xs text-slate-500">{timeAgo(req.arrived_at)}</span>
            </div>

            {/* Body */}
            <div className="px-4 py-3 space-y-2">
              <div className="flex items-start gap-2">
                <span className="text-xs text-slate-500 w-16 flex-shrink-0 pt-px">Peer</span>
                <span className="text-xs font-mono text-violet-300 truncate">
                  {req.sender_peer_id}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-slate-500 w-16 flex-shrink-0">Protocolo</span>
                <span className={`text-xs font-mono border rounded px-1.5 py-0.5 ${badgeCls}`}>
                  {req.requested_transport.toUpperCase()}
                </span>
              </div>
              <p className="text-xs text-slate-500 pt-0.5">
                Esto requiere cambiar tu modo de transport.
              </p>
            </div>

            {/* Actions */}
            <div className="flex gap-2 px-4 pb-3">
              <button
                onClick={() => handleAccept(req.request_id)}
                disabled={busy[req.request_id]}
                className="flex-1 text-xs bg-violet-900/60 hover:bg-violet-800/60 text-violet-200 border border-violet-700/60 rounded-lg py-2 font-medium transition-colors disabled:opacity-40"
              >
                {busy[req.request_id] ? "…" : "Aceptar"}
              </button>
              <button
                onClick={() => handleReject(req.request_id)}
                disabled={busy[req.request_id]}
                className="flex-1 text-xs bg-slate-800/60 hover:bg-slate-700/60 text-slate-400 border border-slate-700/60 rounded-lg py-2 transition-colors disabled:opacity-40"
              >
                Rechazar
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
