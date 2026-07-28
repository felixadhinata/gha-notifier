/** App configuration: load/save JSON config, monitored-repo list helpers. */

import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import { app } from "electron";

export interface GithubUser {
  login: string;
  id: number;
}

export interface AppConfig {
  pollIntervalSec: number;
  notifyEnabled: boolean;
  openOnStartup: boolean;
  repos: string[];
  token: string | null;
  user: GithubUser | null;
}

export const DEFAULT_CONFIG: AppConfig = {
  pollIntervalSec: 20,
  notifyEnabled: true,
  openOnStartup: false,
  repos: [],
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
    const merged: AppConfig = { ...DEFAULT_CONFIG };
    for (const key of Object.keys(DEFAULT_CONFIG) as (keyof AppConfig)[]) {
      if (key in raw && raw[key] !== undefined) {
        (merged as any)[key] = (raw as any)[key];
      }
    }
    merged.repos = normalizeRepos(raw.repos);
    return merged;
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
    config.repos.filter((r): r is string => typeof r === "string" && r.trim().length > 0).map((r) => r.trim())
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
  return true;
}

function normalizeRepos(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];
  const repos: string[] = [];
  for (const entry of raw) {
    if (typeof entry === "string" && entry.trim()) {
      repos.push(entry.trim());
    } else if (entry && typeof entry === "object") {
      const owner = String((entry as any).owner || "").trim();
      const repo = String((entry as any).repo || "").trim();
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
