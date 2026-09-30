import { contextBridge, ipcRenderer } from "electron";

// Expose the agent base URL so the UI can reach it.
contextBridge.exposeInMainWorld("rsAgent", {
  baseUrl: "http://127.0.0.1:8000",
  openExternal: (url: string) => ipcRenderer.send("open-external", url),
  onOidcCallback: (callback: (url: string) => void) => {
    console.log("[preload] Subscribing to oidc-callback IPC");
    ipcRenderer.removeAllListeners("oidc-callback");
    ipcRenderer.on("oidc-callback", (_event, url) => {
      console.log("[preload] Received oidc-callback IPC, invoking frontend callback");
      callback(url);
    });
  },
  onLog: (callback: (msg: string) => void) => {
    ipcRenderer.on("oidc-log", (_event, msg) => callback(msg));
  },
  winMinimize: () => ipcRenderer.send("win-minimize"),
  winMaximize: () => ipcRenderer.send("win-maximize"),
  winClose: () => ipcRenderer.send("win-close"),
  onMaximizeChange: (callback: (isMaximized: boolean) => void) => {
    ipcRenderer.removeAllListeners("win-maximized");
    ipcRenderer.on("win-maximized", (_event, v: boolean) => callback(v));
  },
  getLoginItemEnabled: (): Promise<boolean> =>
    ipcRenderer.invoke("get-login-item"),
  setLoginItemEnabled: (enabled: boolean): Promise<void> =>
    ipcRenderer.invoke("set-login-item", enabled),
});
