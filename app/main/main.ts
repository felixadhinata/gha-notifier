import * as path from "path";
import { app, BrowserWindow, ipcMain, Menu, nativeImage, shell, Tray } from "electron";

import { fetchGhCliToken, validateToken } from "./auth";
import { AppConfig, DEFAULT_CONFIG, addRepo, getRepos, loadConfig, removeRepo, saveConfig, setOpenOnStartup } from "./config";
import { GitHubClient } from "./github";
import { pollAllRepos, repoStatusFromRuns, RepoStatus } from "./repoService";
import { GithubRun } from "./github";

const ASSETS_DIR = path.join(__dirname, "..", "..", "assets");
const TRAY_RUNS_PER_REPO = 8;
const isTrayOnly = process.argv.includes("--tray-only");

let config: AppConfig = loadConfig();
let client: GitHubClient = new GitHubClient(config.token);
let mainWindow: BrowserWindow | null = null;
let tray: Tray | null = null;
let pollTimer: NodeJS.Timeout | null = null;
let isPolling = false;
let runsByRepo: Record<string, GithubRun[]> = {};

// ---------------------------------------------------------------------------
// Window
// ---------------------------------------------------------------------------

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1140,
    height: 720,
    minWidth: 380,
    minHeight: 160,
    title: "GHA Notifier",
    icon: path.join(ASSETS_DIR, "icon.png"),
    webPreferences: {
      preload: path.join(__dirname, "..", "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
    show: !isTrayOnly,
  });
  mainWindow.loadFile(path.join(__dirname, "..", "renderer", "index.html"));

  mainWindow.on("close", (event) => {
    if ((app as any).isQuitting) return;
    event.preventDefault();
    mainWindow?.hide();
  });
}

function showWindow(): void {
  if (!mainWindow) {
    createWindow();
    return;
  }
  mainWindow.show();
  mainWindow.focus();
}

// ---------------------------------------------------------------------------
// Tray
// ---------------------------------------------------------------------------

function trayIconPath(status: RepoStatus): string {
  return path.join(ASSETS_DIR, `icon-${status}.png`);
}

function pickOverallStatus(): RepoStatus {
  const priority: RepoStatus[] = ["yellow", "red", "green", "gray"];
  const present = new Set(getRepos(config).map((r) => repoStatusFromRuns(runsByRepo[r])));
  for (const p of priority) {
    if (present.has(p)) return p;
  }
  return "gray";
}

function rebuildTrayMenu(): void {
  if (!tray) return;
  tray.setImage(nativeImage.createFromPath(trayIconPath(pickOverallStatus())));

  const template: Electron.MenuItemConstructorOptions[] = [];
  for (const repoKey of getRepos(config)) {
    const runs = (runsByRepo[repoKey] || []).slice(0, TRAY_RUNS_PER_REPO);
    const submenu: Electron.MenuItemConstructorOptions[] = runs.map((run) => {
      const status = repoStatusFromRuns([run]);
      const emoji = { yellow: "🟡", green: "🟢", red: "🔴", gray: "⚪" }[status];
      const branch = run.head_branch || "—";
      const commit = (run.head_commit?.message || "—").trim().split("\n")[0];
      return {
        label: `${emoji} ${run.name || "Workflow"} · ${branch}`,
        sublabel: commit,
        enabled: Boolean(run.html_url),
        click: () => run.html_url && shell.openExternal(run.html_url),
      };
    });
    template.push({
      label: repoKey,
      submenu: submenu.length ? submenu : [{ label: "No runs yet", enabled: false }],
    });
  }
  if (template.length) template.push({ type: "separator" });
  template.push(
    { label: "Open", click: showWindow },
    { label: "Refresh", click: () => void refreshRuns() },
    { type: "separator" },
    {
      label: "Quit",
      click: () => {
        (app as any).isQuitting = true;
        app.quit();
      },
    }
  );
  tray.setContextMenu(Menu.buildFromTemplate(template));
}

function setupTray(): void {
  if (tray) return;
  tray = new Tray(nativeImage.createFromPath(trayIconPath("gray")));
  tray.setToolTip("GHA Notifier");
  tray.on("click", showWindow);
  rebuildTrayMenu();
}

// ---------------------------------------------------------------------------
// Polling
// ---------------------------------------------------------------------------

async function refreshRuns(): Promise<void> {
  if (isPolling) return;
  isPolling = true;
  try {
    const result = await pollAllRepos(config, client);
    runsByRepo = result.runsByRepo;
    rebuildTrayMenu();
    mainWindow?.webContents.send("repo-runs-updated", runsByRepo);
  } finally {
    isPolling = false;
  }
}

function startPolling(): void {
  if (pollTimer) clearInterval(pollTimer);
  const intervalSec = Math.max(10, config.pollIntervalSec || 20);
  pollTimer = setInterval(() => void refreshRuns(), intervalSec * 1000);
}

// ---------------------------------------------------------------------------
// IPC
// ---------------------------------------------------------------------------

function getAutostartExecCommand(): string {
  return `${process.execPath} --tray-only`;
}

ipcMain.handle("auth:get-state", () => ({ user: config.user }));

ipcMain.handle("auth:sign-in-gh", async () => {
  const token = await fetchGhCliToken();
  if (!token) {
    return { ok: false, error: "Could not get token from gh. Install it (e.g. apt install gh) and run: gh auth login" };
  }
  return signInWithToken(token);
});

ipcMain.handle("auth:sign-in-token", async (_event, token: string) => signInWithToken(token));

async function signInWithToken(token: string) {
  try {
    const result = await validateToken(token);
    config.token = result.token;
    config.user = { login: result.login, id: result.id };
    client = new GitHubClient(result.token);
    saveConfig(config);
    startPolling();
    void refreshRuns();
    return { ok: true, user: config.user };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

ipcMain.handle("auth:sign-out", () => {
  config = { ...DEFAULT_CONFIG };
  saveConfig(config);
  client = new GitHubClient(null);
  runsByRepo = {};
  startPolling();
  rebuildTrayMenu();
  return { ok: true };
});

ipcMain.handle("repos:list", () => ({ repos: getRepos(config), runsByRepo }));

ipcMain.handle("repos:add", (_event, repoKey: string) => {
  const added = addRepo(config, repoKey);
  if (added) {
    saveConfig(config);
    void refreshRuns();
  }
  return { added, repos: getRepos(config) };
});

ipcMain.handle("repos:remove", (_event, repoKey: string) => {
  const removed = removeRepo(config, repoKey);
  if (removed) {
    saveConfig(config);
    delete runsByRepo[repoKey];
    rebuildTrayMenu();
  }
  return { removed, repos: getRepos(config) };
});

ipcMain.handle("repos:refresh", async () => {
  await refreshRuns();
  return { repos: getRepos(config), runsByRepo };
});

ipcMain.handle("repos:search-mine", async () => {
  if (!client.token) return { repos: [] };
  try {
    const repos = await client.getUserRepos();
    return { repos: repos.map((r) => r.full_name).sort() };
  } catch {
    return { repos: [] };
  }
});

ipcMain.handle("settings:get", () => ({
  pollIntervalSec: config.pollIntervalSec,
  notifyEnabled: config.notifyEnabled,
  openOnStartup: config.openOnStartup,
}));

ipcMain.handle(
  "settings:save",
  (_event, settings: { pollIntervalSec: number; notifyEnabled: boolean; openOnStartup: boolean }) => {
    config.pollIntervalSec = settings.pollIntervalSec;
    config.notifyEnabled = settings.notifyEnabled;
    config.openOnStartup = settings.openOnStartup;
    saveConfig(config);
    startPolling();
    setOpenOnStartup(config.openOnStartup, getAutostartExecCommand());
    return { ok: true };
  }
);

ipcMain.handle("shell:open-external", (_event, url: string) => shell.openExternal(url));

// ---------------------------------------------------------------------------
// App lifecycle
// ---------------------------------------------------------------------------

app.whenReady().then(() => {
  Menu.setApplicationMenu(null);
  createWindow();
  setupTray();
  startPolling();
  void refreshRuns();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
    else showWindow();
  });
});

app.on("window-all-closed", () => {
  // Keep running in the tray; quitting is explicit via the tray menu.
});

app.on("before-quit", () => {
  (app as any).isQuitting = true;
});
