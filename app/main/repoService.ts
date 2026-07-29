/**
 * Fetch and track GitHub Actions runs triggered by the signed-in user across monitored repos.
 * Mirrors src(python)/repo_service.py from the previous GTK build.
 */

import { Notification, shell } from "electron";
import type { AppConfig } from "./config";
import { getWorkflowFilter } from "./config";
import type { GitHubClient, GithubRun } from "./github";

// GitHub's max per_page. Fetching the full page (instead of a small slice) means the
// renderer has enough history in memory to paginate/filter the runs table client-side
// without extra round-trips.
const RUNS_PER_REPO = 100;

/** run id -> currently in-progress/queued, tracked so we notify exactly once per completed run. */
const trackedActiveRunIds = new Set<number>();

function isInProgress(run: GithubRun): boolean {
  const status = (run.status || "").toLowerCase();
  return status === "in_progress" || status === "queued";
}

/** A repo's workflow filter (if any) restricts notifications to the selected workflow names. */
function matchesWorkflowFilter(config: AppConfig, repoKey: string, run: GithubRun): boolean {
  const filter = getWorkflowFilter(config, repoKey);
  if (filter.length === 0) return true;
  return filter.includes(run.name || "Workflow");
}

async function fetchMyRuns(
  client: GitHubClient,
  owner: string,
  repo: string,
  login: string,
  perPage = RUNS_PER_REPO,
): Promise<GithubRun[]> {
  try {
    return await client.getRunsForActor(owner, repo, login, perPage);
  } catch {
    return [];
  }
}

export type RepoStatus = "yellow" | "green" | "red" | "gray";

/** Aggregate status dot for a repo: yellow (a run is active) > green/red (last completed) > gray (no runs). */
export function repoStatusFromRuns(runs: GithubRun[] | undefined): RepoStatus {
  if (!runs || runs.length === 0) return "gray";
  if (runs.some(isInProgress)) return "yellow";
  const top = runs[0];
  if (top.status === "completed") {
    return top.conclusion === "success" ? "green" : "red";
  }
  return "gray";
}

function formatDuration(startedAt: string | null, updatedAt: string | null): string {
  if (!startedAt) return "n/a";
  const start = Date.parse(startedAt);
  if (Number.isNaN(start)) return "n/a";
  const end = updatedAt ? Date.parse(updatedAt) : Date.now();
  if (Number.isNaN(end)) return "n/a";
  const seconds = Math.max(0, Math.round((end - start) / 1000));
  const minutes = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return minutes === 0 ? `${secs}s` : `${minutes}m ${secs}s`;
}

function notifyCompleted(repoKey: string, run: GithubRun): void {
  const success = run.conclusion === "success";
  const emoji = success ? "🟢" : "🔴";
  const result = success ? "succeeded" : "failed";
  const name = run.name || "Workflow";
  const branch = run.head_branch || "—";
  const rawCommit = (run.head_commit?.message || "").trim().split("\n")[0].slice(0, 60).trim() || "—";
  const duration = formatDuration(run.run_started_at, run.updated_at) || "—";

  const notification = new Notification({
    title: repoKey,
    body: `${emoji} ${name} ${result}\n${branch}\n${rawCommit}\nDuration: ${duration}`,
  });
  if (run.html_url) {
    notification.on("click", () => shell.openExternal(run.html_url));
  }
  notification.show();
}

interface PollResult {
  runsByRepo: Record<string, GithubRun[]>;
}

/** Fetch recent runs for every monitored repo; fire notifications for runs that just completed. */
export async function pollAllRepos(
  config: AppConfig,
  client: GitHubClient | null,
  onNotify?: () => void,
): Promise<PollResult> {
  const runsByRepo: Record<string, GithubRun[]> = {};
  const login = config.user?.login;
  if (!login || !client?.token) {
    return { runsByRepo };
  }
  for (const repoKey of config.repos || []) {
    if (!repoKey.includes("/")) continue;
    const [owner, repo] = repoKey.split("/", 2);
    const runs = await fetchMyRuns(client, owner, repo, login);
    runsByRepo[repoKey] = runs;
    for (const run of runs) {
      if (run.id == null) continue;
      if (isInProgress(run)) {
        trackedActiveRunIds.add(run.id);
      } else if (trackedActiveRunIds.has(run.id)) {
        trackedActiveRunIds.delete(run.id);
        if (config.notifyEnabled && matchesWorkflowFilter(config, repoKey, run)) {
          notifyCompleted(repoKey, run);
          onNotify?.();
        }
      }
    }
  }
  return { runsByRepo };
}
