/** Minimal GitHub REST API client (uses the global fetch bundled with Electron/Node). */

// Overridable for local testing against a mock server; defaults to the real API.
const GITHUB_API = process.env.GHA_NOTIFIER_API_BASE || "https://api.github.com";

interface GithubActor {
  login: string;
}

export interface GithubRun {
  id: number;
  name: string;
  status: string; // "queued" | "in_progress" | "completed"
  conclusion: string | null;
  head_branch: string;
  created_at: string;
  run_started_at: string | null;
  updated_at: string;
  html_url: string;
  actor: GithubActor | null;
  head_commit: { message: string } | null;
}

export class GitHubClient {
  constructor(public token: string | null) {}

  private async requestJson<T>(url: string): Promise<T> {
    const headers: Record<string, string> = {
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
    };
    if (this.token) headers.Authorization = `Bearer ${this.token}`;
    const res = await fetch(url, { headers });
    if (!res.ok) {
      throw new Error(`GitHub API ${res.status}: ${await res.text()}`);
    }
    return (await res.json()) as T;
  }

  getCurrentUser(): Promise<{ login: string; id: number }> {
    return this.requestJson(`${GITHUB_API}/user`);
  }

  getUserRepos(perPage = 100): Promise<Array<{ full_name: string }>> {
    return this.requestJson(`${GITHUB_API}/user/repos?per_page=${perPage}&sort=updated`);
  }

  async getRunsForActor(owner: string, repo: string, actor: string, perPage = 100): Promise<GithubRun[]> {
    const url =
      `${GITHUB_API}/repos/${owner}/${repo}/actions/runs` + `?per_page=${perPage}&actor=${encodeURIComponent(actor)}`;
    const data = await this.requestJson<{ workflow_runs: GithubRun[] }>(url);
    return data.workflow_runs || [];
  }
}
