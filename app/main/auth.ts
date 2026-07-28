/** Sign-in helpers: fetch a token from the `gh` CLI, or validate a pasted personal access token. */

import { execFile } from "node:child_process";
import { GitHubClient } from "./github";

export function fetchGhCliToken(): Promise<string | null> {
  return new Promise((resolve) => {
    execFile("gh", ["auth", "token"], { timeout: 10_000 }, (error, stdout) => {
      if (error) {
        resolve(null);
        return;
      }
      const token = stdout.trim();
      resolve(token || null);
    });
  });
}

export interface LoginResult {
  token: string;
  login: string;
  id: number;
}

/** Validate a token against GitHub and return the signed-in user, or throw on failure. */
export async function validateToken(token: string): Promise<LoginResult> {
  const client = new GitHubClient(token);
  const user = await client.getCurrentUser();
  return { token, login: user.login, id: user.id };
}
