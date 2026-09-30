import { useEffect, useRef, useState } from "react";
import type { AppConfig, FileMetadata, PeerInfo, TransferResult } from "../types";
import { serverApi, getAgentUrl } from "../api";
import FileList from "../components/FileList";
import PeerList from "../components/PeerList";
import TransferDialog from "../components/TransferDialog";
import AdminPanel from "../components/AdminPanel";
import IncomingConnectionsBanner from "../components/IncomingConnectionsBanner";
import TransportRequestBanner from "../components/TransportRequestBanner";
import TitleBar from "../components/TitleBar";
import TopBar from "../components/TopBar";
import ErrorPage from "./ErrorPage";
import ArchiveTab from "../components/tabs/ArchiveTab";
import ConfigTab from "../components/tabs/ConfigTab";

type Tab = "peers" | "archive" | "admin" | "config";

interface Props {
  config: AppConfig;
  onDisconnect: () => void;
}

interface NavItemProps {
  active: boolean;
  onClick: () => void;
  label: string;
  icon: React.ReactNode;
  accent?: string;
}

function NavItem({ active, onClick, label, icon, accent }: NavItemProps) {
  const activeClass = active
    ? accent === "amber"
      ? "bg-amber-950/60 text-amber-400"
      : "bg-brand-900 text-brand-400"
    : `text-slate-600 hover:text-slate-300 hover:bg-slate-800${accent === "amber" ? " hover:text-amber-400" : ""}`;

  return (
    <button
      onClick={onClick}
      title={label}
      className={`flex items-center gap-3 w-full px-3 py-2.5 rounded-lg transition-colors ${activeClass}`}
    >
      <span className="w-5 h-5 flex items-center justify-center flex-shrink-0">
        {icon}
      </span>
      <span className="text-xs font-medium whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity duration-150 delay-75 overflow-hidden">
        {label}
      </span>
    </button>
  );
}

export default function DashboardPage({ config, onDisconnect }: Props) {
  const [peers, setPeers] = useState<PeerInfo[]>([]);
  const [serverOnline, setServerOnline] = useState(true);
  const [transferTarget, setTransferTarget] = useState<{ peer: PeerInfo; file?: FileMetadata } | null>(null);
  const [isAdmin, setIsAdmin] = useState(false);
  const [activeTab, setActiveTab] = useState<Tab>("peers");
  const wsRef = useRef<WebSocket | null>(null);

  // Detect admin
  useEffect(() => {
    serverApi.getScopes().then(() => setIsAdmin(true)).catch(() => setIsAdmin(false));
  }, [config.serverUrl, config.token]);

  // WebSocket peer discovery
  useEffect(() => {
    let retryTimer: ReturnType<typeof setTimeout>;

    function connect() {
      const ws = serverApi.watchPeers(config.serverUrl, config.token);
      wsRef.current = ws;

      ws.onopen = () => setServerOnline(true);

      ws.onmessage = (ev) => {
        try {
          const list: PeerInfo[] = JSON.parse(ev.data);
          setPeers(list.filter((p) => p.peer_id !== config.peerId));
        } catch {}
      };

      ws.onerror = () => setServerOnline(false);

      ws.onclose = () => {
        setServerOnline(false);
        retryTimer = setTimeout(connect, 5000);
      };
    }

    connect();
    return () => {
      clearTimeout(retryTimer);
      wsRef.current?.close();
    };
  }, [config.serverUrl, config.peerId, config.token]);

  const handleSendFromPeer = (peer: PeerInfo) =>
    setTransferTarget({ peer });

  const handleSendFromFile = (file: FileMetadata, peer?: PeerInfo) => {
    if (peer) {
      setTransferTarget({ peer, file });
    } else {
      const online = peers.find((p) => p.online);
      if (online) setTransferTarget({ peer: online, file });
    }
  };

  const handleTransferComplete = (_result: TransferResult) => {
    setTransferTarget(null);
  };

  function handleRetry() {
    wsRef.current?.close();
  }

  if (!serverOnline) {
    return (
      <>
        <TitleBar />
        <ErrorPage onRetry={handleRetry} onDisconnect={onDisconnect} />
      </>
    );
  }

  return (
    <div className="flex flex-col h-screen bg-slate-950 overflow-hidden">
      <TitleBar />

      <TopBar
        serverOnline={serverOnline}
        peerId={config.peerId}
        onDisconnect={onDisconnect}
      />

      {/* Body: expandable sidebar + content */}
      <div className="flex flex-1 min-h-0">
        {/* Expandable icon sidebar — expands on hover via CSS group */}
        <nav className="group w-14 hover:w-48 bg-slate-900 border-r border-slate-800 flex flex-col py-3 px-1.5 gap-1 flex-shrink-0 transition-[width] duration-200 overflow-hidden">

          {/* Peers */}
          <NavItem
            active={activeTab === "peers"}
            onClick={() => setActiveTab("peers")}
            label="Peers"
            icon={
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="9" cy="7" r="4" />
                <path d="M3 21v-2a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v2" />
                <path d="M16 3a4 4 0 0 1 0 8" />
                <path d="M21 21v-2a4 4 0 0 0-3-3.87" />
              </svg>
            }
          />

          {/* Archivo */}
          <NavItem
            active={activeTab === "archive"}
            onClick={() => setActiveTab("archive")}
            label="Archivo"
            icon={
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
              </svg>
            }
          />

          {/* Admin — only visible when admin */}
          {isAdmin ? (
            <NavItem
              active={activeTab === "admin"}
              onClick={() => setActiveTab("admin")}
              label="Admin"
              accent="amber"
              icon={
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="3" />
                  <path d="M19.07 4.93a10 10 0 0 0-14.14 0M4.93 19.07a10 10 0 0 0 14.14 0" />
                </svg>
              }
            />
          ) : null}

          {/* Configuración */}
          <NavItem
            active={activeTab === "config"}
            onClick={() => setActiveTab("config")}
            label="Configuración"
            icon={
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="3" />
                <path d="M19.07 4.93a10 10 0 0 0-14.14 0M4.93 19.07a10 10 0 0 0 14.14 0M12 2v2m0 16v2M2 12h2m16 0h2M4.93 4.93l1.41 1.41m11.32 11.32l1.41 1.41M4.93 19.07l1.41-1.41m11.32-11.32l1.41-1.41" />
              </svg>
            }
          />
        </nav>

        {/* Main content area */}
        <main className="flex-1 min-w-0 overflow-auto">
          {activeTab === "peers" && (
            <div className="flex gap-4 p-4 h-full">
              <div className="w-80 flex-shrink-0">
                <FileList peers={peers} onSend={handleSendFromFile} />
              </div>
              <div className="flex-1 flex flex-col gap-4 min-w-0">
                <PeerList peers={peers} currentPeerId={config.peerId} onSend={handleSendFromPeer} />
                <IncomingConnectionsBanner />
                <TransportRequestBanner />
              </div>
            </div>
          )}

          {activeTab === "archive" && (
            <div className="p-4 h-full">
              <ArchiveTab peerId={config.peerId} />
            </div>
          )}

          {activeTab === "admin" && isAdmin ? (
            <AdminPanel />
          ) : null}

          {activeTab === "config" && (
            <div className="p-4 h-full">
              <ConfigTab
                peerId={config.peerId}
                agentUrl={getAgentUrl()}
                serverUrl={config.serverUrl}
              />
            </div>
          )}
        </main>
      </div>

      {/* Transfer dialog */}
      {transferTarget ? (
        <TransferDialog
          peer={transferTarget.peer}
          preselectedFile={transferTarget.file}
          serverUrl={config.serverUrl}
          peerId={config.peerId}
          onComplete={handleTransferComplete}
          onClose={() => setTransferTarget(null)}
        />
      ) : null}
    </div>
  );
}
