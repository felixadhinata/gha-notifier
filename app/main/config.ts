/** App configuration: load/save JSON config, monitored-repo list helpers. */

import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { app } from "electron";

export interface GithubUser {
  login: string;
  id: number;
}

export type Theme = "system" | "light" | "dark";
export type NotificationSound = "none" | "default" | "chime" | "ping" | "bell" | "pop" | "alert";

export interface AppConfig {
  pollIntervalSec: number;
  notifyEnabled: boolean;
  notificationSound: NotificationSound;
  openOnStartup: boolean;
  theme: Theme;
  repos: string[];
  /** repoKey -> workflow names to notify for. Empty/missing means "notify for all workflows". */
  workflowFilters: Record<string, string[]>;
  token: string | null;
  user: GithubUser | null;
}

export const DEFAULT_CONFIG: AppConfig = {
  pollIntervalSec: 20,
  notifyEnabled: true,
  notificationSound: "default",
  openOnStartup: true,
  theme: "system",
  repos: [],
  workflowFilters: {},
  token: null,
  user: null,
};

function getConfigPath(): string {
  return path.join(app.getPath("userData"), "config.json");
}

export function loadConfig(): AppConfig {
  const configPath = getConfigPath();
  if (!fs.existsSync(configPath)) {
    return { ...DEFAULT_CONFIG };
  }
  try {
    const raw = JSON.parse(fs.readFileSync(configPath, "utf-8")) as Partial<AppConfig> & {
      repos?: unknown;
    };
    return {
      pollIntervalSec: raw.pollIntervalSec ?? DEFAULT_CONFIG.pollIntervalSec,
      notifyEnabled: raw.notifyEnabled ?? DEFAULT_CONFIG.notifyEnabled,
      notificationSound: raw.notificationSound ?? DEFAULT_CONFIG.notificationSound,
      openOnStartup: raw.openOnStartup ?? DEFAULT_CONFIG.openOnStartup,
      theme: raw.theme ?? DEFAULT_CONFIG.theme,
      repos: normalizeRepos(raw.repos),
      workflowFilters: normalizeWorkflowFilters(raw.workflowFilters),
      token: raw.token ?? DEFAULT_CONFIG.token,
      user: raw.user ?? DEFAULT_CONFIG.user,
    };
  } catch {
    return { ...DEFAULT_CONFIG };
  }
}

export function saveConfig(config: AppConfig): void {
  const configPath = getConfigPath();
  fs.mkdirSync(path.dirname(configPath), { recursive: true });
  fs.writeFileSync(configPath, JSON.stringify(config, null, 2), "utf-8");
}

/** Sorted list of monitored "owner/repo" strings. */
export function getRepos(config: AppConfig): string[] {
  if (!Array.isArray(config.repos)) return [];
  const set = new Set(
    config.repos.filter((r): r is string => typeof r === "string" && r.trim().length > 0).map((r) => r.trim()),
  );
  return Array.from(set).sort();
}

/** Add a repo ("owner/repo") if not already present. Returns true if added. */
export function addRepo(config: AppConfig, repoKey: string): boolean {
  const trimmed = (repoKey || "").trim();
  const [owner, repo] = trimmed.split("/", 2);
  if (!owner || !repo) return false;
  const repos = getRepos(config);
  if (repos.includes(trimmed)) return false;
  repos.push(trimmed);
  config.repos = repos.sort();
  return true;
}

/** Remove a repo from config.repos. Returns true if it was present. */
export function removeRepo(config: AppConfig, repoKey: string): boolean {
  const repos = getRepos(config);
  if (!repos.includes(repoKey)) return false;
  config.repos = repos.filter((r) => r !== repoKey);
  delete config.workflowFilters[repoKey];
  return true;
}

/** Workflow names to notify for on a repo. Empty means "all workflows". */
export function getWorkflowFilter(config: AppConfig, repoKey: string): string[] {
  return config.workflowFilters[repoKey] || [];
}

/** Set (or clear, if empty) the workflow notification filter for a repo. */
export function setWorkflowFilter(config: AppConfig, repoKey: string, workflows: string[]): void {
  const cleaned = Array.from(new Set(workflows.map((w) => w.trim()).filter(Boolean))).sort();
  if (cleaned.length === 0) {
    delete config.workflowFilters[repoKey];
  } else {
    config.workflowFilters[repoKey] = cleaned;
  }
}

function normalizeWorkflowFilters(raw: unknown): Record<string, string[]> {
  if (!raw || typeof raw !== "object") return {};
  const result: Record<string, string[]> = {};
  for (const [repoKey, value] of Object.entries(raw as Record<string, unknown>)) {
    if (!Array.isArray(value)) continue;
    const names = value.filter((v): v is string => typeof v === "string" && v.trim().length > 0);
    if (names.length > 0) result[repoKey] = names;
  }
  return result;
}

function normalizeRepos(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];
  const repos: string[] = [];
  for (const entry of raw) {
    if (typeof entry === "string" && entry.trim()) {
      repos.push(entry.trim());
    } else if (entry && typeof entry === "object") {
      const record = entry as Record<string, unknown>;
      const owner = String(record.owner || "").trim();
      const repo = String(record.repo || "").trim();
      if (owner && repo) repos.push(`${owner}/${repo}`);
    }
  }
  return Array.from(new Set(repos)).sort();
}

// ---------------------------------------------------------------------------
// Open-on-startup (Linux XDG autostart)
// ---------------------------------------------------------------------------

function getAutostartDesktopPath(): string {
  const configDir = process.env.XDG_CONFIG_HOME || path.join(os.homedir(), ".config");
  return path.join(configDir, "autostart", "com.gha.notifier.desktop");
}

export function setOpenOnStartup(enabled: boolean, execCommand: string): void {
  const desktopPath = getAutostartDesktopPath();
  if (!enabled) {
    try {
      if (fs.existsSync(desktopPath)) fs.unlinkSync(desktopPath);
    } catch {
      /* ignore */
    }
    return;
  }
  if (!execCommand.trim()) return;
  try {
    fs.mkdirSync(path.dirname(desktopPath), { recursive: true });
    const content = `[Desktop Entry]
Type=Application
Name=GHA Notifier
Comment=GitHub Actions workflow notifications
Exec=${execCommand}
Terminal=false
X-GNOME-Autostart-enabled=true
`;
    fs.writeFileSync(desktopPath, content, "utf-8");
  } catch {
    /* ignore */
  }
}
