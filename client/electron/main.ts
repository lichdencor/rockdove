import { app, BrowserWindow, shell, ipcMain, IpcMainInvokeEvent } from "electron";
import { spawn, ChildProcess } from "child_process";
import * as path from "path";
import * as http from "http";

const AGENT_PORT = 8000;
let agentProcess: ChildProcess | null = null;
let mainWindow: BrowserWindow | null = null;

// Handle opening URLs in the system browser
ipcMain.on("open-external", (_event, url) => {
  shell.openExternal(url);
});

ipcMain.on("win-minimize", () => mainWindow?.minimize());
ipcMain.on("win-maximize", () => {
  if (mainWindow?.isMaximized()) mainWindow?.unmaximize();
  else mainWindow?.maximize();
});
ipcMain.on("win-close", () => mainWindow?.close());

ipcMain.handle("get-login-item", (_event: IpcMainInvokeEvent): boolean => {
  return app.getLoginItemSettings().openAtLogin;
});

ipcMain.handle("set-login-item", (_event: IpcMainInvokeEvent, enabled: boolean): void => {
  app.setLoginItemSettings({
    openAtLogin: enabled,
    openAsHidden: true,
    name: "RockDove",
  });
});

function resolveAgent(): { cmd: string; args: string[]; cwd: string } {
  if (app.isPackaged) {
    const ext = process.platform === "win32" ? ".exe" : "";
    const bin = path.join(process.resourcesPath, "agent", `rs-agent${ext}`);
    return { cmd: bin, args: [], cwd: path.dirname(bin) };
  }
  return {
    cmd: "uv",
    args: ["run", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", String(AGENT_PORT)],
    cwd: path.join(__dirname, "..", "..", "agent"),
  };
}

function startAgent(): void {
  const { cmd, args, cwd } = resolveAgent();
  agentProcess = spawn(cmd, args, { cwd, env: { ...process.env }, stdio: "pipe" });
  agentProcess.stdout?.on("data", (d) => process.stdout.write(`[agent] ${d}`));
  agentProcess.stderr?.on("data", (d) => process.stderr.write(`[agent] ${d}`));
  agentProcess.on("error", (e) => console.error("[agent] spawn error:", e.message));
}

function stopAgent(): void {
  agentProcess?.kill();
  agentProcess = null;
}

function waitForAgent(maxAttempts = 40): Promise<void> {
  return new Promise((resolve, reject) => {
    let n = 0;
    const try_ = () => {
      const req = http.get(`http://127.0.0.1:${AGENT_PORT}/health`, (res) => {
        res.resume();
        if (res.statusCode === 200) resolve();
        else retry();
      });
      req.setTimeout(400);
      req.on("error", retry);
    };
    const retry = () => {
      if (++n >= maxAttempts) return reject(new Error("Agent health check timed out"));
      setTimeout(try_, 500);
    };
    try_();
  });
}

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    show: false,
    title: "RockDove",
    frame: false,
    titleBarStyle: "hidden",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
    },
  });

  mainWindow.once("ready-to-show", () => mainWindow?.show());

  if (app.isPackaged) {
    mainWindow.loadFile(path.join(process.resourcesPath, "ui", "dist", "index.html"));
  } else {
    mainWindow.loadURL(process.env.VITE_DEV_URL ?? "http://localhost:5173");
  }

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url === "about:blank" || !url.startsWith("http")) {
      return { action: "allow" };
    }
    shell.openExternal(url);
    return { action: "deny" };
  });
}

// Windows/Linux deep link handling
const gotTheLock = app.requestSingleInstanceLock();

if (!gotTheLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });

  app.whenReady().then(async () => {
    startAgent();
    try {
      await waitForAgent();
    } catch (err) {
      console.error("[main]", err);
    }
    createWindow();
    mainWindow?.on("maximize", () => mainWindow?.webContents.send("win-maximized", true));
    mainWindow?.on("unmaximize", () => mainWindow?.webContents.send("win-maximized", false));
  });
}

app.on("window-all-closed", () => {
  stopAgent();
  if (process.platform !== "darwin") app.quit();
});

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});
