import json
import urllib.parse
import urllib.request


GITHUB_API = "https://api.github.com"
DEVICE_CODE_URL = "https://github.com/login/device/code"
TOKEN_URL = "https://github.com/login/oauth/access_token"


class GitHubClient:
    def __init__(self, token=None):
        self.token = token

    def _request_json(self, url, data=None, headers=None, method=None):
        payload = None
        if data is not None:
            payload = urllib.parse.urlencode(data).encode("utf-8")
        req = urllib.request.Request(url, data=payload, method=method or "POST")
        final_headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if headers:
            final_headers.update(headers)
        if self.token:
            final_headers["Authorization"] = f"Bearer {self.token}"
        for key, value in final_headers.items():
            req.add_header(key, value)
        with urllib.request.urlopen(req, timeout=30) as response:
            body = response.read().decode("utf-8")
            return json.loads(body)

    def get_current_user(self):
        return self._request_json(f"{GITHUB_API}/user", data=None, method="GET")

    def get_user_repos(self, per_page=100):
        url = f"{GITHUB_API}/user/repos?per_page={per_page}&sort=updated"
        return self._request_json(url, data=None, method="GET")

    def start_device_flow(self, client_id):
        data = {
            "client_id": client_id,
            "scope": "repo,workflow,read:user",
        }
        return self._request_json(
            DEVICE_CODE_URL,
            data=data,
            headers={"Accept": "application/json"},
            method="POST",
        )

    def poll_device_token(self, client_id, device_code):
        data = {
            "client_id": client_id,
            "device_code": device_code,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        }
        return self._request_json(
            TOKEN_URL,
            data=data,
            headers={"Accept": "application/json"},
            method="POST",
        )

    def get_branches(self, owner, repo, page=1, per_page=100):
        url = f"{GITHUB_API}/repos/{owner}/{repo}/branches?per_page={per_page}&page={page}"
        return self._request_json(url, data=None, method="GET")

    def get_pulls(self, owner, repo, state="open", page=1, per_page=100):
        url = f"{GITHUB_API}/repos/{owner}/{repo}/pulls?state={state}&per_page={per_page}&page={page}"
        return self._request_json(url, data=None, method="GET")

    def get_pull(self, owner, repo, pull_number):
        """Fetch a single PR (includes head.ref for branch name)."""
        url = f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{pull_number}"
        return self._request_json(url, data=None, method="GET")

    def search_issues(self, q, page=1, per_page=100):
        """Search issues/PRs. q e.g. 'repo:owner/repo type:pr author:login is:open'."""
        url = f"{GITHUB_API}/search/issues?q={urllib.parse.quote(q)}&per_page={per_page}&page={page}"
        return self._request_json(url, data=None, method="GET")

    def get_runs(self, owner, repo, branch, status=None):
        """List workflow runs for branch. status: None (all), 'in_progress', 'completed', etc."""
        url = f"{GITHUB_API}/repos/{owner}/{repo}/actions/runs?per_page=20&branch={urllib.parse.quote(branch)}"
        if status:
            url += f"&status={urllib.parse.quote(status)}"
        return self._request_json(url, data=None, method="GET")

    def get_run(self, owner, repo, run_id):
        """Fetch a single workflow run by id. Returns run dict or empty on error."""
        if not run_id:
            return {}
        url = f"{GITHUB_API}/repos/{owner}/{repo}/actions/runs/{int(run_id)}"
        try:
            return self._request_json(url, data=None, method="GET")
        except Exception:
            return {}
