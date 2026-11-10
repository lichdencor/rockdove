import { useCallback, useEffect, useState } from "react";
import type { TransferResult } from "../../types";
import { agentApi } from "../../api";

interface Props {
  peerId: string;
}

const STATUS_COLORS: Record<string, string> = {
  ok: "text-emerald-400 bg-emerald-950/50 border-emerald-800",
  degraded: "text-yellow-400 bg-yellow-950/50 border-yellow-800",
  failed: "text-red-400 bg-red-950/50 border-red-800",
  pending: "text-slate-400 bg-slate-800/50 border-slate-700",
};

// ── Horizontal bar chart: recovery ratio per peer ────────────────────────────

interface PeerStat {
  peer_id: string;
  ratio: number; // recovered_blocks / total_blocks — higher means more errors
  count: number;
}

function InstabilityChart({ transfers }: { transfers: TransferResult[] }) {
  const relevant = transfers.filter((t) => t.total_blocks > 0 && t.file_id !== null);

  // Group by transfer_id, pick last per peer to approximate peer_id (not in TransferResult)
  // Since TransferResult has no peer_id, we group by file_id as proxy
  const byFile: Record<string, { ratio: number; count: number }> = {};
  for (const t of relevant) {
    const key = t.file_id ?? t.transfer_id;
    if (!byFile[key]) byFile[key] = { ratio: 0, count: 0 };
    byFile[key].ratio += t.recovered_blocks / t.total_blocks;
    byFile[key].count += 1;
  }

  const stats: PeerStat[] = Object.entries(byFile)
    .map(([id, v]) => ({
      peer_id: id.slice(0, 12),
      ratio: v.count > 0 ? v.ratio / v.count : 0,
      count: v.count,
    }))
    .sort((a, b) => b.ratio - a.ratio)
    .slice(0, 5);

  if (stats.length === 0) {
    return (
      <p className="text-xs text-slate-600 italic py-2">Sin datos de bloques aún.</p>
    );
  }

  const BAR_H = 22;
  const GAP = 8;
  const LABEL_W = 100;
  const CHART_W = 300;
  const BAR_MAX = CHART_W - LABEL_W - 40;
  const svgH = stats.length * (BAR_H + GAP) + 8;

  return (
    <svg viewBox={`0 0 ${CHART_W} ${svgH}`} className="w-full max-w-xs" aria-label="Instabilidad por archivo">
      {stats.map((s, i) => {
        const y = i * (BAR_H + GAP) + 4;
        const barW = Math.max(4, s.ratio * BAR_MAX);
        // Color: low ratio = emerald, mid = yellow, high = red
        const fill = s.ratio < 0.15 ? "#34d399" : s.ratio < 0.4 ? "#facc15" : "#f87171";
        return (
          <g key={s.peer_id}>
            <text x="0" y={y + BAR_H / 2 + 4} fontSize="9" fill="#94a3b8" fontFamily="monospace">
              {s.peer_id}
            </text>
            <rect
              x={LABEL_W}
              y={y}
              width={barW}
              height={BAR_H}
              rx="3"
              fill={fill}
              opacity="0.8"
            />
            <text
              x={LABEL_W + barW + 4}
              y={y + BAR_H / 2 + 4}
              fontSize="9"
              fill="#94a3b8"
            >
              {Math.round(s.ratio * 100)}%
            </text>
          </g>
        );
      })}
    </svg>
  );
}

// ── Donut chart: ok+degraded vs failed ────────────────────────────────────────

function SuccessDonut({ transfers }: { transfers: TransferResult[] }) {
  const total = transfers.length;
  if (total === 0) {
    return <p className="text-xs text-slate-600 italic py-2">Sin transferencias aún.</p>;
  }

  const failed = transfers.filter((t) => t.status === "failed").length;
  const success = total - failed;
  const successPct = Math.round((success / total) * 100);
  const failedPct = 100 - successPct;

  // SVG donut: two arcs on a circle of r=40, cx=60 cy=60
  const R = 40;
  const CX = 60;
  const CY = 60;
  const STROKE = 12;
  const CIRCUMFERENCE = 2 * Math.PI * R;
  const successDash = (success / total) * CIRCUMFERENCE;
  const failedDash = CIRCUMFERENCE - successDash;

  return (
    <div className="flex items-center gap-4">
      <svg viewBox="0 0 120 120" className="w-20 h-20 flex-shrink-0" aria-label="Tasa de éxito">
        {/* Background ring */}
        <circle
          cx={CX} cy={CY} r={R}
          fill="none"
          stroke="#1e293b"
          strokeWidth={STROKE}
        />
        {/* Failed arc (red, drawn first = behind) */}
        {failed > 0 && (
          <circle
            cx={CX} cy={CY} r={R}
            fill="none"
            stroke="#f87171"
            strokeWidth={STROKE}
            strokeDasharray={`${failedDash} ${successDash}`}
            strokeDashoffset={0}
            strokeLinecap="butt"
            transform={`rotate(${(success / total) * 360 - 90} ${CX} ${CY})`}
          />
        )}
        {/* Success arc (emerald) */}
        {success > 0 && (
          <circle
            cx={CX} cy={CY} r={R}
            fill="none"
            stroke="#34d399"
            strokeWidth={STROKE}
            strokeDasharray={`${successDash} ${failedDash}`}
            strokeDashoffset={0}
            strokeLinecap="butt"
            transform={`rotate(-90 ${CX} ${CY})`}
          />
        )}
        {/* Center label */}
        <text x={CX} y={CY - 4} textAnchor="middle" fontSize="13" fontWeight="600" fill="#e2e8f0">
          {successPct}%
        </text>
        <text x={CX} y={CY + 10} textAnchor="middle" fontSize="8" fill="#64748b">
          éxito
        </text>
      </svg>

      <div className="text-xs space-y-1.5">
        <div className="flex items-center gap-2">
          <span className="w-2.5 h-2.5 rounded-full bg-emerald-400 flex-shrink-0" />
          <span className="text-slate-400">exitosos</span>
          <span className="text-slate-200 font-mono ml-auto pl-4">{successPct}%</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-2.5 h-2.5 rounded-full bg-red-400 flex-shrink-0" />
          <span className="text-slate-400">fallidos</span>
          <span className="text-slate-200 font-mono ml-auto pl-4">{failedPct}%</span>
        </div>
        <p className="text-slate-600 pt-1">{total} total</p>
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export default function ArchiveTab({ peerId: _peerId }: Props) {
  const [transfers, setTransfers] = useState<TransferResult[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const list = await agentApi.listTransfers();
      setTransfers(list);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const interval = setInterval(load, 5000);
    return () => clearInterval(interval);
  }, [load]);

  return (
    <div className="space-y-6 overflow-auto h-full">
      {/* ── Transfer list ── */}
      <section>
        <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
          Transferencias
        </h3>

        {loading && (
          <p className="text-xs text-slate-600">Cargando…</p>
        )}

        {error && (
          <p className="text-xs text-red-400 bg-red-950/40 border border-red-900 rounded-lg px-3 py-2">
            {error}
          </p>
        )}

        {!loading && !error && transfers.length === 0 && (
          <p className="text-xs text-slate-600 italic">Sin transferencias registradas.</p>
        )}

        {transfers.length > 0 && (
          <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
            <div className="overflow-auto max-h-64">
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-slate-900 border-b border-slate-800">
                  <tr className="text-slate-500 text-left">
                    <th className="px-4 py-2.5 font-medium">ID</th>
                    <th className="px-3 py-2.5 font-medium">Dir</th>
                    <th className="px-3 py-2.5 font-medium">Estado</th>
                    <th className="px-3 py-2.5 font-medium">Bloques</th>
                    <th className="px-3 py-2.5 font-medium">Archivo</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/50">
                  {transfers.map((t) => {
                    const statusCls =
                      STATUS_COLORS[t.status] ?? STATUS_COLORS.pending;
                    return (
                      <tr key={t.transfer_id} className="hover:bg-slate-800/30 transition-colors">
                        <td className="px-4 py-2 font-mono text-slate-500 truncate max-w-[90px]">
                          {t.transfer_id.slice(0, 8)}
                        </td>
                        <td className="px-3 py-2 text-slate-400">
                          {t.file_id ? "↑" : "↓"}
                        </td>
                        <td className="px-3 py-2">
                          <span className={`border rounded px-1.5 py-0.5 font-mono ${statusCls}`}>
                            {t.status}
                          </span>
                        </td>
                        <td className="px-3 py-2 font-mono text-slate-400">
                          {t.total_blocks > 0
                            ? `${t.recovered_blocks}/${t.total_blocks}`
                            : "—"}
                        </td>
                        <td className="px-3 py-2 font-mono text-slate-500 truncate max-w-[80px]">
                          {t.file_id?.slice(0, 8) ?? "—"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </section>

      {/* ── Instability chart ── */}
      <section>
        <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
          Instabilidad por archivo (bloques recuperados)
        </h3>
        <div className="bg-slate-800/40 rounded-lg border border-slate-700/50 p-4">
          <InstabilityChart transfers={transfers} />
        </div>
      </section>

      {/* ── Success donut ── */}
      <section>
        <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
          Tasa de transferencias exitosas
        </h3>
        <div className="bg-slate-800/40 rounded-lg border border-slate-700/50 p-4">
          <SuccessDonut transfers={transfers} />
        </div>
      </section>
    </div>
  );
}
