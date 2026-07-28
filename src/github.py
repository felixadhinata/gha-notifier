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

    def get_runs_for_actor(self, owner, repo, actor, per_page=20):
        """List workflow runs across all branches triggered by `actor`, most recent first."""
        url = (
            f"{GITHUB_API}/repos/{owner}/{repo}/actions/runs"
            f"?per_page={per_page}&actor={urllib.parse.quote(actor)}"
        )
        return self._request_json(url, data=None, method="GET")
