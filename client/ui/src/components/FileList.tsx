import { useCallback, useEffect, useRef, useState } from "react";
import type { FileMetadata, PeerInfo } from "../types";
import { agentApi, getAgentUrl } from "../api";

interface Props {
  peers: PeerInfo[];
  onSend: (file: FileMetadata, peer?: PeerInfo) => void;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}

export default function FileList({ peers, onSend }: Props) {
  const [files, setFiles] = useState<FileMetadata[]>([]);
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const loadFiles = useCallback(async () => {
    try {
      const list = await agentApi.listFiles();
      setFiles(list);
    } catch {
      // agent may not be running yet
    }
  }, []);

  useEffect(() => {
    loadFiles();
    const interval = setInterval(loadFiles, 5000);
    return () => clearInterval(interval);
  }, [loadFiles]);

  async function uploadFile(file: File) {
    setUploading(true);
    setError(null);
    try {
      await agentApi.uploadFile(file);
      await loadFiles();
    } catch (e) {
      setError(`Error subiendo archivo: ${(e as Error).message}`);
    } finally {
      setUploading(false);
    }
  }

  async function deleteFile(fileId: string) {
    try {
      await agentApi.deleteFile(fileId);
      setFiles((prev) => prev.filter((f) => f.file_id !== fileId));
    } catch (e) {
      setError(`Error eliminando: ${(e as Error).message}`);
    }
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) uploadFile(file);
  }

  const onlinepeers = peers.filter((p) => p.online);

  return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden h-full flex flex-col">
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
        <h2 className="text-sm font-medium text-slate-200">Mis archivos</h2>
        <button
          onClick={() => inputRef.current?.click()}
          disabled={uploading}
          className="flex items-center gap-1.5 text-xs bg-brand-600 hover:bg-brand-700 disabled:opacity-40 text-white rounded-lg px-3 py-1.5 transition-colors"
        >
          <span>+</span>
          {uploading ? "Subiendo…" : "Subir"}
        </button>
        <input
          ref={inputRef}
          type="file"
          className="hidden"
          onChange={(e) => e.target.files?.[0] && uploadFile(e.target.files[0])}
        />
      </div>

      {/* Drop zone */}
      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        className={`flex-1 overflow-auto transition-colors ${dragOver ? "bg-brand-900/20 border-2 border-dashed border-brand-500" : ""}`}
      >
        {error && (
          <p className="mx-4 mt-3 text-xs text-red-400 bg-red-950/40 border border-red-900 rounded-lg px-3 py-2">
            {error}
          </p>
        )}

        {files.length === 0 ? (
          <div className="px-4 py-10 text-center text-slate-600 text-sm">
            <div className="text-3xl mb-2">📁</div>
            Arrastrá archivos o usá el botón Subir
          </div>
        ) : (
          <ul className="divide-y divide-slate-800/50">
            {files.map((file) => (
              <li key={file.file_id} className="flex items-center gap-3 px-4 py-3 hover:bg-slate-800/40 group transition-colors">
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-slate-200 truncate">{file.filename}</p>
                  <p className="text-xs text-slate-500 mt-0.5 font-mono">
                    {formatBytes(file.size)}
                  </p>
                </div>

                <div className="flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                  {onlinepeers.length > 0 ? (
                    onlinepeers.length === 1 ? (
                      <button
                        onClick={() => onSend(file, onlinepeers[0])}
                        className="text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white border border-slate-700 rounded-lg px-2.5 py-1 transition-colors"
                      >
                        Enviar
                      </button>
                    ) : (
                      <button
                        onClick={() => onSend(file)}
                        className="text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white border border-slate-700 rounded-lg px-2.5 py-1 transition-colors"
                      >
                        Enviar…
                      </button>
                    )
                  ) : null}
                  <a
                    href={`${getAgentUrl()}/files/${file.file_id}`}
                    download={file.filename}
                    className="text-xs text-slate-600 hover:text-slate-300 transition-colors px-1"
                    title="Descargar"
                  >
                    ↓
                  </a>
                  <button
                    onClick={() => deleteFile(file.file_id)}
                    className="text-xs text-slate-600 hover:text-red-400 transition-colors px-1"
                    title="Eliminar"
                  >
                    ✕
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
