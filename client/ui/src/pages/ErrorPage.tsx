import { useEffect, useRef, useState } from "react";

interface Props {
  onRetry: () => void;
  onDisconnect: () => void;
}

const COUNTDOWN_START = 20;

export default function ErrorPage({ onRetry, onDisconnect }: Props) {
  const [countdown, setCountdown] = useState(COUNTDOWN_START);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  function startCountdown() {
    setCountdown(COUNTDOWN_START);
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = setInterval(() => {
      setCountdown((prev) => {
        if (prev <= 1) {
          clearInterval(timerRef.current!);
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
  }

  // When countdown hits 0, call onRetry
  useEffect(() => {
    if (countdown === 0) {
      onRetry();
      startCountdown();
    }
  }, [countdown]);

  useEffect(() => {
    startCountdown();
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  function handleRetry() {
    onRetry();
    startCountdown();
  }

  return (
    <div className="min-h-screen bg-slate-950 flex items-center justify-center px-4">
      <div className="text-center max-w-sm w-full">
        {/* Pulsing wifi-off icon */}
        <div className="flex justify-center mb-6">
          <div className="relative">
            <span className="absolute inset-0 rounded-full bg-red-500/20 animate-ping" />
            <div className="relative w-16 h-16 rounded-full bg-red-950/60 border border-red-800/60 flex items-center justify-center">
              <svg
                className="w-8 h-8 text-red-400"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                {/* Wifi-off */}
                <line x1="1" y1="1" x2="23" y2="23" />
                <path d="M16.72 11.06A10.94 10.94 0 0 1 19 12.55" />
                <path d="M5 12.55a10.94 10.94 0 0 1 5.17-2.39" />
                <path d="M10.71 5.05A16 16 0 0 1 22.56 9" />
                <path d="M1.42 9a15.91 15.91 0 0 1 4.7-2.88" />
                <path d="M8.53 16.11a6 6 0 0 1 6.95 0" />
                <circle cx="12" cy="20" r="1" fill="currentColor" />
              </svg>
            </div>
          </div>
        </div>

        <h1 className="text-xl font-semibold text-slate-100 mb-2">
          Servidor no disponible
        </h1>
        <p className="text-sm text-slate-500 mb-8">
          Reconectando en{" "}
          <span className="text-slate-300 font-mono tabular-nums">{countdown}s</span>
          …
        </p>

        <div className="flex flex-col gap-3">
          <button
            onClick={handleRetry}
            className="w-full bg-brand-600 hover:bg-brand-700 text-white rounded-lg py-2.5 text-sm font-medium transition-colors"
          >
            Reintentar ahora
          </button>
          <button
            onClick={onDisconnect}
            className="w-full text-slate-500 hover:text-slate-300 text-sm transition-colors py-1"
          >
            Volver a servidores
          </button>
        </div>
      </div>
    </div>
  );
}
