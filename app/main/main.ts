import * as path from "node:path";
import { app, BrowserWindow, ipcMain, Menu, Notification, nativeImage, shell, Tray } from "electron";

import { fetchGhCliToken, validateToken } from "./auth";
import {
  type AppConfig,
  addRepo,
  DEFAULT_CONFIG,
  getRepos,
  getWorkflowFilter,
  loadConfig,
  type NotificationSound,
  removeRepo,
  saveConfig,
  setOpenOnStartup,
  setWorkflowFilter,
  type Theme,
} from "./config";
import { GitHubClient, type GithubRun } from "./github";
import { formatDuration, pollAllRepos, type RepoStatus, repoStatusFromRuns } from "./repoService";

// Custom flag distinguishing "hide to tray" from an actual quit, so window "close" can
// be intercepted while still allowing the tray's Quit item to exit for real.
declare global {
  namespace Electron {
    interface App {
      isQuitting?: boolean;
    }
  }
}

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

/** Same "which workflows to notify for" filter also decides what the tray tracks/shows. */
function matchesTrayFilter(repoKey: string, run: GithubRun): boolean {
  const filter = getWorkflowFilter(config, repoKey);
  if (filter.length === 0) return true;
  return filter.includes(run.name || "Workflow");
}

function updateTrayWatches(): void {
  for (const repoKey of getRepos(config)) {
    for (const run of runsByRepo[repoKey] || []) {
      if (!matchesTrayFilter(repoKey, run)) {
        // Filter narrowed after this run was already tracked: drop it.
        trayWatches.delete(run.id);
        continue;
      }
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
    if (app.isQuitting) return;
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

// Re-setting the tray image to the same icon every poll makes some Linux tray hosts
// briefly flicker/blink it, even though the pixels are identical — only touch it when
// the status actually changed.
let lastTrayIconStatus: RepoStatus | null = null;

// Tracks whether the tray's popup menu is currently open, so a poll-triggered rebuild
// doesn't yank the menu out from under the user mid-click by replacing it while it's
// showing. Instead, the rebuild is deferred until the menu actually closes.
//
// Opening a submenu (e.g. hovering a repo to see its runs) can itself fire a spurious
// menu-will-close on some Linux tray backends, even though the top-level menu is still
// up — debounce the close so a rebuild doesn't sneak in and snap the submenu shut while
// the user is still looking at it.
let trayMenuOpen = false;
let trayMenuRebuildPending = false;
let trayMenuCloseTimer: NodeJS.Timeout | null = null;
const TRAY_MENU_CLOSE_DEBOUNCE_MS = 400;

function buildTrayMenuTemplate(): Electron.MenuItemConstructorOptions[] {
  const byRepo = new Map<string, TrayWatchEntry[]>();
  for (const entry of trayWatches.values()) {
    let entries = byRepo.get(entry.repoKey);
    if (!entries) {
      entries = [];
      byRepo.set(entry.repoKey, entries);
    }
    entries.push(entry);
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
      const duration = formatDuration(run.run_started_at, isRunInProgress(run) ? null : run.updated_at);
      return {
        label: `${emoji} ${run.name || "Workflow"} · ${branch} · ${duration}`,
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
        app.isQuitting = true;
        app.quit();
      },
    },
  );
  return template;
}

function rebuildTrayMenu(): void {
  if (!tray) return;
  const status = pickOverallStatus();
  if (status !== lastTrayIconStatus) {
    lastTrayIconStatus = status;
    tray.setImage(nativeImage.createFromPath(trayIconPath(status)));
  }

  if (trayMenuOpen) {
    trayMenuRebuildPending = true;
    return;
  }

  const menu = Menu.buildFromTemplate(buildTrayMenuTemplate());
  menu.on("menu-will-show", () => {
    trayMenuOpen = true;
    if (trayMenuCloseTimer) {
      clearTimeout(trayMenuCloseTimer);
      trayMenuCloseTimer = null;
    }
  });
  menu.on("menu-will-close", () => {
    if (trayMenuCloseTimer) clearTimeout(trayMenuCloseTimer);
    trayMenuCloseTimer = setTimeout(() => {
      trayMenuCloseTimer = null;
      trayMenuOpen = false;
      if (trayMenuRebuildPending) {
        trayMenuRebuildPending = false;
        rebuildTrayMenu();
      }
    }, TRAY_MENU_CLOSE_DEBOUNCE_MS);
  });
  tray.setContextMenu(menu);
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

// Notifications are shown from the main process, but actually playing a sound needs the
// renderer's Audio element (no audio API exists on the main-process side), so this just
// forwards the choice to whichever window is around to play it.
function playNotificationSound(sound: NotificationSound): void {
  if (sound === "none") return;
  mainWindow?.webContents.send("play-notification-sound", sound);
}

async function refreshRuns(): Promise<void> {
  if (isPolling) return;
  isPolling = true;
  try {
    const result = await pollAllRepos(config, client, () => playNotificationSound(config.notificationSound));
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

ipcMain.handle("workflow-filter:get", (_event, repoKey: string) => ({
  workflows: getWorkflowFilter(config, repoKey),
}));

ipcMain.handle("workflow-filter:set", (_event, repoKey: string, workflows: string[]) => {
  setWorkflowFilter(config, repoKey, workflows);
  saveConfig(config);
  return { ok: true };
});

ipcMain.handle("settings:get", () => ({
  pollIntervalSec: config.pollIntervalSec,
  notifyEnabled: config.notifyEnabled,
  notificationSound: config.notificationSound,
  openOnStartup: config.openOnStartup,
  theme: config.theme,
}));

ipcMain.handle("app:get-version", () => app.getVersion());

ipcMain.handle("notifications:test", (_event, sound: NotificationSound) => {
  const notification = new Notification({
    title: "GHA Notifier",
    body: "🔔 Test notification — if you can see (and hear) this, notifications are working.",
  });
  notification.show();
  playNotificationSound(sound);
  return { ok: true };
});

// Saved immediately on selection (not gated behind Settings' Apply button) so a sound
// choice can't be silently discarded by closing the modal via Cancel/backdrop-click —
// matches "Send test notification", which already always plays the current selection.
ipcMain.handle("notifications:set-sound", (_event, sound: NotificationSound) => {
  config.notificationSound = sound;
  saveConfig(config);
  return { ok: true };
});

ipcMain.handle(
  "settings:save",
  (
    _event,
    settings: {
      pollIntervalSec: number;
      notifyEnabled: boolean;
      notificationSound: NotificationSound;
      openOnStartup: boolean;
      theme: Theme;
    },
  ) => {
    config.pollIntervalSec = settings.pollIntervalSec;
    config.notifyEnabled = settings.notifyEnabled;
    config.notificationSound = settings.notificationSound;
    config.openOnStartup = settings.openOnStartup;
    config.theme = settings.theme;
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
  setOpenOnStartup(config.openOnStartup, getAutostartExecCommand());
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
  app.isQuitting = true;
});
