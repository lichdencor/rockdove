import type { PeerInfo } from "../types";

interface Props {
  peers: PeerInfo[];
  currentPeerId: string;
  onSend: (peer: PeerInfo) => void;
}

type PeerStatus = "online" | "unknown" | "offline";

const UNKNOWN_THRESHOLD_S = 300;

function getPeerStatus(peer: PeerInfo): PeerStatus {
  if (peer.online) return "online";
  try {
    const ageSec = (Date.now() - new Date(peer.last_seen).getTime()) / 1000;
    return ageSec < UNKNOWN_THRESHOLD_S ? "unknown" : "offline";
  } catch {
    return "offline";
  }
}

function timeAgo(iso: string): string {
  const diffS = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (diffS < 60) return `${diffS}s`;
  if (diffS < 3600) return `${Math.floor(diffS / 60)}m`;
  return `${Math.floor(diffS / 3600)}h`;
}

const STATUS_DOT: Record<PeerStatus, string> = {
  online:  "bg-emerald-400",
  unknown: "bg-amber-400 animate-pulse",
  offline: "bg-slate-600",
};

const STATUS_LABEL: Record<PeerStatus, string> = {
  online:  "online",
  unknown: "desconocido",
  offline: "offline",
};

const STATUS_TEXT: Record<PeerStatus, string> = {
  online:  "text-slate-600",
  unknown: "text-amber-600",
  offline: "text-slate-600",
};

const TRANSPORT_BADGE: Record<string, string> = {
  quic: "text-violet-400 bg-violet-950/50 border-violet-800",
  udp:  "text-slate-500 bg-slate-800/50 border-slate-700",
};

function PeerRow({
  peer,
  currentPeerId,
  currentOwner,
  onSend,
}: {
  peer: PeerInfo;
  currentPeerId: string;
  currentOwner: string | null;
  onSend: (peer: PeerInfo) => void;
}) {
  const status = getPeerStatus(peer);
  const transport = peer.transport ?? "udp";
  const badgeCls = TRANSPORT_BADGE[transport] ?? TRANSPORT_BADGE.udp;
  const isSelf = peer.peer_id === currentPeerId;
  const isOwnDevice = !isSelf && currentOwner != null && peer.owner === currentOwner;

  return (
    <li className="flex items-center gap-3 px-4 py-3 hover:bg-slate-800/40 transition-colors">
      <div className={`w-2 h-2 rounded-full flex-shrink-0 ${STATUS_DOT[status]}`} />

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-mono text-slate-200 truncate">
            {peer.peer_id}
          </span>
          {isSelf && (
            <span className="text-xs bg-brand-900 text-brand-400 rounded px-1.5 py-0.5">
              yo
            </span>
          )}
          {isOwnDevice && (
            <span className="text-xs bg-slate-800 text-slate-400 border border-slate-700 rounded px-1.5 py-0.5">
              mi dispositivo
            </span>
          )}
          <span className={`text-xs font-mono border rounded px-1.5 py-0.5 ${badgeCls}`}>
            {transport.toUpperCase()}
          </span>
          {peer.relay_capable && (
            <span className="text-[10px] text-brand-400 bg-brand-950/50 border border-brand-800 rounded px-1.5 py-0.5">
              relay
            </span>
          )}
          {peer.relay_tags?.includes("gateway") && (
            <span className="text-[10px] text-violet-400 bg-violet-950/50 border border-violet-800 rounded px-1.5 py-0.5">
              gateway
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 mt-0.5">
          <span className="text-xs text-slate-500 truncate">
            {peer.udp_host}:{peer.udp_port}
          </span>
          <span className={`text-xs ${STATUS_TEXT[status]}`}>
            · {status === "online"
                ? `hace ${timeAgo(peer.last_seen)}`
                : STATUS_LABEL[status]}
          </span>
        </div>
      </div>

      {status === "online" && !isSelf ? (
        <button
          onClick={() => onSend(peer)}
          className={`flex-shrink-0 text-xs border rounded-lg px-3 py-1.5 transition-colors ${
            isOwnDevice
              ? "bg-brand-950/30 hover:bg-brand-900/50 text-brand-400 border-brand-800"
              : "bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white border-slate-700"
          }`}
        >
          {isOwnDevice ? "Transferir" : "Enviar"}
        </button>
      ) : status !== "online" && !isSelf ? (
        <span className={`flex-shrink-0 text-xs ${STATUS_TEXT[status]}`}>
          {STATUS_LABEL[status]}
        </span>
      ) : null}
    </li>
  );
}

export default function PeerList({ peers, currentPeerId, onSend }: Props) {
  const online  = peers.filter((p) => p.online);
  const notOnline = peers.filter((p) => !p.online);

  const currentOwner = peers.find((p) => p.peer_id === currentPeerId)?.owner ?? null;

  // If any peer has an owner set, group by owner; otherwise flat list
  const hasOwners = peers.some((p) => p.owner);

  const header = (
    <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
      <h2 className="text-sm font-medium text-slate-200">Peers de la red</h2>
      {peers.length > 0 && (
        <span className="text-xs text-slate-500">
          {online.length} online
          {notOnline.length > 0 ? ` · ${notOnline.length} inactivos` : ""}
        </span>
      )}
    </div>
  );

  if (peers.length === 0) {
    return (
      <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
        {header}
        <div className="px-4 py-10 text-center text-slate-600 text-sm">
          <div className="text-3xl mb-2">📡</div>
          Esperando peers… el agente se registra automáticamente al arrancar.
        </div>
      </div>
    );
  }

  const sorted = [...online, ...notOnline];

  if (!hasOwners) {
    return (
      <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
        {header}
        <ul className="divide-y divide-slate-800/50">
          {sorted.map((peer) => (
            <PeerRow
              key={peer.peer_id}
              peer={peer}
              currentPeerId={currentPeerId}
              currentOwner={currentOwner}
              onSend={onSend}
            />
          ))}
        </ul>
      </div>
    );
  }

  // Group by owner
  const groups = new Map<string, PeerInfo[]>();
  for (const peer of sorted) {
    const key = peer.owner ?? peer.peer_id;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push(peer);
  }

  return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
      {header}
      {Array.from(groups.entries()).map(([owner, groupPeers]) => {
        const isCurrentOwner = owner === currentOwner;
        const onlineCount = groupPeers.filter((p) => p.online).length;
        return (
          <div key={owner}>
            <div className={`flex items-center gap-2 px-4 py-1.5 border-b border-slate-800/50 ${
              isCurrentOwner ? "bg-brand-950/20" : "bg-slate-800/20"
            }`}>
              <span className={`text-[11px] font-medium ${
                isCurrentOwner ? "text-brand-400" : "text-slate-400"
              }`}>
                {owner}
              </span>
              {isCurrentOwner && (
                <span className="text-[10px] text-brand-600">· yo</span>
              )}
              <span className="ml-auto text-[10px] text-slate-600">
                {onlineCount}/{groupPeers.length} online
              </span>
            </div>
            <ul className="divide-y divide-slate-800/50">
              {groupPeers.map((peer) => (
                <PeerRow
                  key={peer.peer_id}
                  peer={peer}
                  currentPeerId={currentPeerId}
                  currentOwner={currentOwner}
                  onSend={onSend}
                />
              ))}
            </ul>
          </div>
        );
      })}
    </div>
  );
}
