import { contextBridge, ipcRenderer } from "electron";
import type { GithubUser, Theme } from "./main/config";
import type { GithubRun } from "./main/github";

export interface Settings {
  pollIntervalSec: number;
  notifyEnabled: boolean;
  openOnStartup: boolean;
  theme: Theme;
}

export type SignInResult = { ok: true; user: GithubUser } | { ok: false; error: string };

export interface GhaApi {
  getAuthState(): Promise<{ user: GithubUser | null }>;
  signInWithGh(): Promise<SignInResult>;
  signInWithToken(token: string): Promise<SignInResult>;
  signOut(): Promise<{ ok: boolean }>;

  listRepos(): Promise<{ repos: string[]; runsByRepo: Record<string, GithubRun[]> }>;
  addRepo(repoKey: string): Promise<{ added: boolean; repos: string[] }>;
  removeRepo(repoKey: string): Promise<{ removed: boolean; repos: string[] }>;
  refreshRepos(): Promise<{ repos: string[]; runsByRepo: Record<string, GithubRun[]> }>;
  searchMyRepos(): Promise<{ repos: string[] }>;

  getSettings(): Promise<Settings>;
  saveSettings(settings: Settings): Promise<{ ok: boolean }>;
  getVersion(): Promise<string>;

  openExternal(url: string): Promise<void>;
  onRepoRunsUpdated(callback: (runsByRepo: Record<string, GithubRun[]>) => void): void;
}

const api: GhaApi = {
  getAuthState: () => ipcRenderer.invoke("auth:get-state"),
  signInWithGh: () => ipcRenderer.invoke("auth:sign-in-gh"),
  signInWithToken: (token) => ipcRenderer.invoke("auth:sign-in-token", token),
  signOut: () => ipcRenderer.invoke("auth:sign-out"),

  listRepos: () => ipcRenderer.invoke("repos:list"),
  addRepo: (repoKey) => ipcRenderer.invoke("repos:add", repoKey),
  removeRepo: (repoKey) => ipcRenderer.invoke("repos:remove", repoKey),
  refreshRepos: () => ipcRenderer.invoke("repos:refresh"),
  searchMyRepos: () => ipcRenderer.invoke("repos:search-mine"),

  getSettings: () => ipcRenderer.invoke("settings:get"),
  saveSettings: (settings) => ipcRenderer.invoke("settings:save", settings),
  getVersion: () => ipcRenderer.invoke("app:get-version"),

  openExternal: (url) => ipcRenderer.invoke("shell:open-external", url),
  onRepoRunsUpdated: (callback) => {
    ipcRenderer.on("repo-runs-updated", (_event, runsByRepo) => callback(runsByRepo));
  },
};

contextBridge.exposeInMainWorld("gha", api);
