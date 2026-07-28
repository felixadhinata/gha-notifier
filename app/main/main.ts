import { app, BrowserWindow, ipcMain, Menu, nativeImage, shell, Tray } from "electron";
import * as path from "path";

import { fetchGhCliToken, validateToken } from "./auth";
import {
  type AppConfig,
  addRepo,
  DEFAULT_CONFIG,
  getRepos,
  loadConfig,
  removeRepo,
  saveConfig,
  setOpenOnStartup,
} from "./config";
import { GitHubClient, type GithubRun } from "./github";
import { pollAllRepos, type RepoStatus, repoStatusFromRuns } from "./repoService";

const ASSETS_DIR = path.join(__dirname, "..", "..", "assets");
const isTrayOnly = process.argv.includes("--tray-only");

let config: AppConfig = loadConfig();
let client: GitHubClient = new GitHubClient(config.token);
let mainWindow: BrowserWindow | null = null;
let tray: Tray | null = null;
let pollTimer: NodeJS.Timeout | null = null;
let isPolling = false;
let runsByRepo: Record<string, GithubRun[]> = {};

// ---------------------------------------------------------------------------
// Tray watch list: only ever gains an entry when a run is caught in_progress/
// queued (never backfilled from history), and keeps showing it — with its
// final status — until "Clear completed" is clicked. Session-only, not
// persisted, same as the notification-dedup tracking in repoService.
// ---------------------------------------------------------------------------

interface TrayWatchEntry {
  repoKey: string;
  run: GithubRun;
}

const trayWatches = new Map<number, TrayWatchEntry>();

function isRunInProgress(run: GithubRun): boolean {
  const status = (run.status || "").toLowerCase();
  return status === "in_progress" || status === "queued";
}

function updateTrayWatches(): void {
  for (const repoKey of getRepos(config)) {
    for (const run of runsByRepo[repoKey] || []) {
      const existing = trayWatches.get(run.id);
      if (existing) {
        existing.run = run;
      } else if (isRunInProgress(run)) {
        trayWatches.set(run.id, { repoKey, run });
      }
    }
  }
}

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

/** Tray icon color, derived from the tray watch list (yellow > red > green > gray). */
function pickOverallStatus(): RepoStatus {
  const entries = [...trayWatches.values()];
  if (entries.length === 0) return "gray";
  if (entries.some((e) => isRunInProgress(e.run))) return "yellow";
  if (entries.some((e) => e.run.conclusion !== "success")) return "red";
  return "green";
}

function rebuildTrayMenu(): void {
  if (!tray) return;
  tray.setImage(nativeImage.createFromPath(trayIconPath(pickOverallStatus())));

  const byRepo = new Map<string, TrayWatchEntry[]>();
  for (const entry of trayWatches.values()) {
    if (!byRepo.has(entry.repoKey)) byRepo.set(entry.repoKey, []);
    byRepo.get(entry.repoKey)!.push(entry);
  }
  for (const entries of byRepo.values()) {
    entries.sort((a, b) => (b.run.created_at || "").localeCompare(a.run.created_at || ""));
  }

  const template: Electron.MenuItemConstructorOptions[] = [];
  for (const repoKey of getRepos(config)) {
    const entries = byRepo.get(repoKey);
    if (!entries || entries.length === 0) continue;
    const submenu: Electron.MenuItemConstructorOptions[] = entries.map(({ run }) => {
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
    template.push({ label: repoKey, submenu });
  }
  if (template.length === 0) {
    template.push({ label: "No runs in progress", enabled: false });
  }

  const hasCompleted = [...trayWatches.values()].some((e) => !isRunInProgress(e.run));
  template.push(
    { type: "separator" },
    {
      label: "Clear completed",
      enabled: hasCompleted,
      click: () => {
        for (const [id, entry] of trayWatches) {
          if (!isRunInProgress(entry.run)) trayWatches.delete(id);
        }
        rebuildTrayMenu();
      },
    },
    { type: "separator" },
    { label: "Open", click: showWindow },
    { label: "Refresh", click: () => void refreshRuns() },
    { type: "separator" },
    {
      label: "Quit",
      click: () => {
        (app as any).isQuitting = true;
        app.quit();
      },
    },
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
    updateTrayWatches();
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
  trayWatches.clear();
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
    for (const [id, entry] of trayWatches) {
      if (entry.repoKey === repoKey) trayWatches.delete(id);
    }
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

ipcMain.handle("app:get-version", () => app.getVersion());

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
  },
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
