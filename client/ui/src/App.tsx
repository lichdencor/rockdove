import { useEffect, useState } from "react";
import type { AppConfig } from "./types";
import ConnectPage from "./pages/ConnectPage";
import DashboardPage from "./pages/DashboardPage";
import TitleBar from "./components/TitleBar";
import { agentApi, serverApi } from "./api";
import { handleCallback, initOidc } from "./auth/oidc";

function loadConfig(): AppConfig | null {
  const serverUrl = localStorage.getItem("serverUrl");
  const peerId = localStorage.getItem("peerId");
  const agentUrl = localStorage.getItem("agentUrl") ?? window.rsAgent?.baseUrl ?? "http://localhost:8000";
  const token = localStorage.getItem("token");
  if (!serverUrl || !peerId) return null;
  return { serverUrl, peerId, agentUrl, token };
}

export default function App() {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [callbackPending, setCallbackPending] = useState(false);

  useEffect(() => {
    // Listen for OIDC callbacks from the main process (Electron only)
    if (window.rsAgent?.onOidcCallback) {
      console.log("[App] Registering OIDC callback listener");
      
      // Capturar logs del proceso Main
      (window.rsAgent as any).onLog?.((msg: string) => console.log(msg));

      window.rsAgent.onOidcCallback(async (url: string) => {
        console.log("[App] Received OIDC callback URL:", url);
        const storedServerUrl = localStorage.getItem("serverUrl");
        if (storedServerUrl) {
          setCallbackPending(true);
          try {
            const cfg = await serverApi.authConfig(storedServerUrl);
            console.log("[App] Auth config fetched:", cfg);
            if (cfg.oidc_enabled && cfg.issuer && cfg.client_id) {
              const redirectUri = "rockdove://callback";
              initOidc(cfg.issuer, cfg.client_id, redirectUri);
              console.log("[App] Processing callback...");
              const user = await handleCallback(url);
              console.log("[App] User authenticated:", user.profile.sub);
              const peerId = (user.profile as any).preferred_username ?? user.profile.sub ?? "oidc-user";
              localStorage.setItem("peerId", peerId);
              localStorage.setItem("token", user.access_token ?? "");
              agentApi.setToken(user.access_token ?? "").catch(() => {});
              setConfig(loadConfig());
            }
          } catch (err) {
            console.error("[App] Auth error:", err);
          } finally {
            setCallbackPending(false);
          }
        } else {
          console.warn("[App] OIDC callback received but no serverUrl in localStorage");
        }
      });
    }

    const url = new URL(window.location.href);
    const isOidcCallback = url.searchParams.has("code") || url.searchParams.has("state");

    if (isOidcCallback) {
      setCallbackPending(true);
      const storedServerUrl = localStorage.getItem("serverUrl");
      if (storedServerUrl) {
        serverApi
          .authConfig(storedServerUrl)
          .then(async (cfg) => {
            if (cfg.oidc_enabled && cfg.issuer && cfg.client_id) {
              const redirectUri = window.location.protocol === "file:" 
                ? window.location.href.split(/[?#]/)[0] 
                : window.location.origin;
              initOidc(cfg.issuer, cfg.client_id, redirectUri);
              const user = await handleCallback();
              const peerId = (user.profile as any).preferred_username ?? user.profile.sub ?? "oidc-user";
              localStorage.setItem("peerId", peerId);
              localStorage.setItem("token", user.access_token ?? "");
              agentApi.setToken(user.access_token ?? "").catch(() => {});
              history.replaceState({}, "", window.location.pathname);
            }
            setCallbackPending(false);
            setConfig(loadConfig());
          })
          .catch(() => {
            setCallbackPending(false);
            setConfig(loadConfig());
          });
      } else {
        setCallbackPending(false);
      }
    } else {
      setConfig(loadConfig());
    }
  }, []);

  const handleDisconnect = () => {
    localStorage.removeItem("serverUrl");
    localStorage.removeItem("peerId");
    localStorage.removeItem("token");
    localStorage.removeItem("inviteToken");
    setConfig(null);
  };

  if (callbackPending) {
    return (
      <div className="flex flex-col min-h-screen bg-slate-950">
        <TitleBar />
        <div className="flex-1 flex items-center justify-center">
          <p className="text-slate-400 text-sm">Completando inicio de sesión…</p>
        </div>
      </div>
    );
  }

  if (!config) {
    return <ConnectPage />;
  }
  return <DashboardPage config={config} onDisconnect={handleDisconnect} />;
}
