import { useEffect, useState } from "react";

export default function TitleBar() {
  const [isMaximized, setIsMaximized] = useState(false);

  useEffect(() => {
    window.rsAgent?.onMaximizeChange?.((val) => {
      setIsMaximized(val);
    });
  }, []);

  // Only render in Electron
  if (!window.rsAgent?.winClose) return null;

  return (
    <div
      className="h-8 bg-slate-950 flex items-center select-none flex-shrink-0"
      style={{ WebkitAppRegion: "drag" } as React.CSSProperties}
    >
      <span className="flex-1 text-center text-xs text-slate-500 font-medium pointer-events-none">
        RockDove
      </span>
      <div
        className="flex items-center"
        style={{ WebkitAppRegion: "no-drag" } as React.CSSProperties}
      >
        {/* Minimize */}
        <button
          onClick={() => window.rsAgent?.winMinimize?.()}
          className="w-8 h-8 flex items-center justify-center text-slate-500 hover:text-white hover:bg-slate-800 transition-colors"
          title="Minimizar"
        >
          <svg width="10" height="1" viewBox="0 0 10 1" fill="currentColor">
            <rect width="10" height="1" />
          </svg>
        </button>

        {/* Maximize / restore */}
        <button
          onClick={() => window.rsAgent?.winMaximize?.()}
          className="w-8 h-8 flex items-center justify-center text-slate-500 hover:text-white hover:bg-slate-800 transition-colors"
          title={isMaximized ? "Restaurar" : "Maximizar"}
        >
          {isMaximized ? (
            // Restore icon (two overlapping squares)
            <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1">
              <rect x="2" y="0" width="8" height="8" />
              <path d="M0 2v8h8" />
            </svg>
          ) : (
            // Maximize icon (single square)
            <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1">
              <rect x="0" y="0" width="10" height="10" />
            </svg>
          )}
        </button>

        {/* Close */}
        <button
          onClick={() => window.rsAgent?.winClose?.()}
          className="w-8 h-8 flex items-center justify-center text-slate-500 hover:text-white hover:bg-red-600 transition-colors"
          title="Cerrar"
        >
          <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
            <line x1="0" y1="0" x2="10" y2="10" />
            <line x1="10" y1="0" x2="0" y2="10" />
          </svg>
        </button>
      </div>
    </div>
  );
}
