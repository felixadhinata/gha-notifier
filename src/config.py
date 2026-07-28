import json
import os

from gi.repository import GLib


DEFAULT_CONFIG = {
    "clientId": None,
    "pollIntervalSec": 20,
    "notifyEnabled": True,
    "openOnStartup": False,
    "repos": [],
    "token": None,
    "user": None,
}


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------

def get_config_path():
    config_dir = os.path.join(GLib.get_user_config_dir(), "gha-notifier")
    return os.path.join(config_dir, "config.json")


def get_autostart_desktop_path():
    """Path to the XDG autostart .desktop file for open-on-startup."""
    return os.path.join(GLib.get_user_config_dir(), "autostart", "com.gha.notifier.desktop")


def set_open_on_startup(enabled, exec_command):
    """
    Enable or disable launching the app at login (Linux XDG autostart).
    exec_command: full command line for Exec= (e.g. "python3 /path/to/app.py").
    """
    path = get_autostart_desktop_path()
    if not enabled:
        try:
            if os.path.isfile(path):
                os.remove(path)
        except OSError:
            pass
        return
    if not (exec_command or "").strip():
        return
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        content = f"""[Desktop Entry]
Type=Application
Name=GHA Notifier
Comment=GitHub Actions workflow notifications
Exec={exec_command}
Terminal=false
X-GNOME-Autostart-enabled=true
"""
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    except OSError:
        pass


def get_repos(config):
    """Return sorted list of monitored 'owner/repo' strings."""
    raw = config.get("repos", [])
    if not isinstance(raw, list):
        return []
    return sorted({r.strip() for r in raw if isinstance(r, str) and r.strip()})


def add_repo(config, repo_key):
    """Add a repo ('owner/repo') to config['repos'] if not already present. Returns True if added."""
    repo_key = (repo_key or "").strip()
    owner, _, repo = repo_key.partition("/")
    if not owner or not repo:
        return False
    repos = get_repos(config)
    if repo_key in repos:
        return False
    repos.append(repo_key)
    config["repos"] = sorted(repos)
    return True


def remove_repo(config, repo_key):
    """Remove a repo from config['repos']. Returns True if it was present."""
    repos = get_repos(config)
    if repo_key not in repos:
        return False
    config["repos"] = [r for r in repos if r != repo_key]
    return True


def load_config():
    path = get_config_path()
    if not os.path.exists(path):
        return DEFAULT_CONFIG.copy()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle) or {}
    except (OSError, json.JSONDecodeError):
        return DEFAULT_CONFIG.copy()
    merged = DEFAULT_CONFIG.copy()
    for key in DEFAULT_CONFIG:
        if key in data:
            merged[key] = data[key]
    merged["repos"] = _normalize_repos(data.get("repos"))
    return merged


def save_config(config):
    path = get_config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(config, handle, indent=2)


# ---------------------------------------------------------------------------
# Private
# ---------------------------------------------------------------------------

def _normalize_repos(raw):
    """Accept either the new plain-string shape or the legacy {owner, repo, ...} dict shape."""
    if not isinstance(raw, list):
        return []
    repos = []
    for entry in raw:
        if isinstance(entry, str) and entry.strip():
            repos.append(entry.strip())
        elif isinstance(entry, dict):
            owner = (entry.get("owner") or "").strip()
            repo = (entry.get("repo") or "").strip()
            if owner and repo:
                repos.append(f"{owner}/{repo}")
    return sorted(set(repos))
