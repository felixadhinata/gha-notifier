import json
import os

from gi.repository import GLib

from models import RepoConfig


DEFAULT_CONFIG = {
    "clientId": None,
    "pollIntervalSec": 5,
    "branchListPollIntervalSec": 30,
    "notifyEnabled": True,
    "openOnStartup": False,
    "repos": [],
    "watches": [],
    "autoWatches": [],
    "token": None,
    "user": None,
}


# ---------------------------------------------------------------------------
# Public (all config functions are public)
# ---------------------------------------------------------------------------

def find_watch(watches, repo, branch, run_id):
    """Return the watch dict matching (repo, branch, runId)."""
    run_id_int = int(run_id or 0)
    for w in watches:
        if w.get("repo") != repo or w.get("branch") != branch:
            continue
        if int(w.get("runId") or 0) == run_id_int:
            return w
    return None


def find_watch_repo_branch(watches, repo, branch):
    """Return the first watch dict for (repo, branch), or None. Used when resolving 'any' watch for this repo/branch."""
    for w in watches:
        if w.get("repo") == repo and w.get("branch") == branch:
            return w
    return None


def get_all_watches(config):
    """Return list of watches from config only (config['watches']). For all watches including auto, use store."""
    watches = config.get("watches", [])
    if not isinstance(watches, list):
        watches = []
    return list(watches)


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
    """Return list of RepoConfig from config['repos']."""
    raw = config.get("repos", [])
    if not isinstance(raw, list):
        raw = []
    return [RepoConfig.from_dict(r) for r in raw]


def load_config():
    path = get_config_path()
    if not os.path.exists(path):
        return DEFAULT_CONFIG.copy()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
            merged = DEFAULT_CONFIG.copy()
            merged.update(data or {})
            # Ensure "watches" and "autoWatches" are always new lists
            raw = merged.get("watches", [])
            merged["watches"] = list(raw) if isinstance(raw, list) else []
            raw_auto = merged.get("autoWatches", [])
            merged["autoWatches"] = list(raw_auto) if isinstance(raw_auto, list) else []
            return merged
    except (OSError, json.JSONDecodeError):
        return DEFAULT_CONFIG.copy()


def save_config(config):
    path = get_config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(config, handle, indent=2)


def set_repos(config, repos):
    """Write config['repos'] from a list of RepoConfig."""
    config["repos"] = [r.to_dict() for r in repos]
