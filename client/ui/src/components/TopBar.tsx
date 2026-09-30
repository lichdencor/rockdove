import { useEffect, useRef, useState } from "react";

function decodeToken(token: string | null): Record<string, unknown> {
  if (!token) return {};
  try {
    const payload = token.split(".")[1];
    return JSON.parse(atob(payload.replace(/-/g, "+").replace(/_/g, "/")));
  } catch {
    return {};
  }
}

interface Props {
  serverOnline: boolean;
  peerId: string;
  onDisconnect: () => void;
}

export default function TopBar({ serverOnline, peerId, onDisconnect }: Props) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const claims = decodeToken(localStorage.getItem("token"));
  const preferredUsername = claims.preferred_username != null ? String(claims.preferred_username) : peerId;
  const sub = claims.sub != null ? String(claims.sub) : "";
  const rawGroups = Array.isArray(claims.groups) ? (claims.groups as unknown[]) : [];
  const groups = rawGroups.map((g) => String(g).replace(/^\//, ""));
  const initials = preferredUsername.slice(0, 2).toUpperCase();

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    if (open) document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  return (
    <div className="h-14 bg-slate-900 border-b border-slate-800 flex items-center px-3 gap-3 flex-shrink-0">
      {/* Static RockDove logo — color reflects server status */}
      <div
        className={`w-9 h-9 flex items-center justify-center rounded-lg flex-shrink-0 ${
          serverOnline ? "text-brand-500" : "text-red-500"
        }`}
        title={serverOnline ? "Servidor online" : "Servidor offline"}
      >
        <svg className="w-8 h-8" viewBox="0 0 24 24" fill="currentColor">
          <path d="M21 5c-2-2-5-2-7 0l-3 4c-1-1-3-1-5 1l-1 2 3-1c1 2 3 3 5 2l1 3-1 4 3-2-1-4c2-1 4-3 4-6l2-2v-1z" />
          <circle cx="17" cy="6" r="1.2" fill="#0f172a" />
        </svg>
      </div>

      {/* Server status dot + label */}
      <div className="flex items-center gap-1.5">
        <span
          className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
            serverOnline ? "bg-emerald-400" : "bg-red-500"
          }`}
        />
        <span className="text-xs text-slate-500">
          {serverOnline ? "online" : "offline"}
        </span>
      </div>

      {/* Right side: user avatar with popup */}
      <div ref={containerRef} className="ml-auto relative">
        <button
          onClick={() => setOpen((v) => !v)}
          className="w-8 h-8 rounded-full bg-brand-700 hover:bg-brand-600 text-white text-xs font-semibold flex items-center justify-center transition-colors ring-2 ring-brand-900 hover:ring-brand-700"
          title={preferredUsername}
        >
          {initials}
        </button>

        {open ? (
          <div className="absolute top-10 right-0 z-50 w-64 bg-slate-900 border border-slate-700 rounded-xl shadow-2xl overflow-hidden">
            {/* User info header */}
            <div className="px-4 py-3 border-b border-slate-800">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-full bg-brand-700 text-white text-sm font-semibold flex items-center justify-center flex-shrink-0">
                  {initials}
                </div>
                <div className="min-w-0">
                  <p className="text-sm font-medium text-slate-200 truncate">{preferredUsername}</p>
                  {sub ? (
                    <p className="text-xs text-slate-500 font-mono truncate" title={sub}>{sub}</p>
                  ) : null}
                </div>
              </div>
            </div>

            {/* Groups */}
            {groups.length > 0 ? (
              <div className="px-4 py-3 border-b border-slate-800">
                <p className="text-xs text-slate-600 mb-2">Grupos</p>
                <div className="flex flex-wrap gap-1.5">
                  {groups.map((g) => (
                    <span
                      key={g}
                      className="text-xs px-2 py-0.5 rounded-full bg-brand-950/60 text-brand-400 border border-brand-800/50"
                    >
                      {g}
                    </span>
                  ))}
                </div>
              </div>
            ) : null}

            {/* Logout */}
            <button
              onClick={() => { setOpen(false); onDisconnect(); }}
              className="w-full flex items-center gap-2.5 px-4 py-2.5 text-xs text-slate-400 hover:text-red-400 hover:bg-slate-800 transition-colors text-left"
            >
              <svg className="w-3.5 h-3.5 flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                <polyline points="16 17 21 12 16 7" />
                <line x1="21" y1="12" x2="9" y2="12" />
              </svg>
              Cerrar sesión
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );
}
