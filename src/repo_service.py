"""
Fetch and track GitHub Actions runs triggered by the signed-in user across monitored repos.
Updates store.repo_runs on the main thread via GLib.idle_add.
"""
import threading

from gi.repository import GLib

from formatters import format_duration
import notify

RUNS_PER_REPO = 20

# run_id -> currently in-progress/queued, tracked across polls so we notify exactly once
# when a run we've seen running transitions to completed (in-memory only, per app session).
_tracked_active_run_ids = set()


def _run_is_in_progress(run):
    return (run.get("status") or "").lower() in ("in_progress", "queued")


def fetch_my_runs(client, owner, repo, login, per_page=RUNS_PER_REPO):
    """Recent workflow runs triggered by `login` in owner/repo, newest first. [] on any error."""
    try:
        return client.get_runs_for_actor(owner, repo, login, per_page=per_page).get("workflow_runs", [])
    except Exception:
        return []


def repo_status_from_runs(runs):
    """Aggregate status dot for a repo: yellow (a run is active) > green/red (last completed) > gray (no runs)."""
    if not runs:
        return "gray"
    if any(_run_is_in_progress(r) for r in runs):
        return "yellow"
    top = runs[0]
    if (top.get("status") or "") == "completed":
        return "green" if top.get("conclusion") == "success" else "red"
    return "gray"


def refresh_repo_runs(on_done=None):
    """Fetch runs for every monitored repo in a background thread; apply to store and notify on main thread."""
    import store

    def worker():
        runs_by_repo, completed_events = _poll_fetch(store.config, store.client)

        def on_main():
            store.repo_runs = runs_by_repo
            for repo_key, run in completed_events:
                _notify_completed(repo_key, run)
            if store.update_tray_menu:
                store.update_tray_menu(force=True)
            if on_done:
                on_done(runs_by_repo)

        GLib.idle_add(on_main)

    threading.Thread(target=worker, daemon=True).start()


# ---------------------------------------------------------------------------
# Private
# ---------------------------------------------------------------------------

def _poll_fetch(config, client):
    """Background-safe: fetch recent runs for every monitored repo. Returns (runs_by_repo, completed_events)."""
    login = (config.get("user") or {}).get("login")
    runs_by_repo = {}
    completed_events = []
    if not login or not client or not client.token:
        return runs_by_repo, completed_events
    for repo_key in config.get("repos") or []:
        if "/" not in repo_key:
            continue
        owner, repo = repo_key.split("/", 1)
        runs = fetch_my_runs(client, owner, repo, login)
        runs_by_repo[repo_key] = runs
        for run in runs:
            run_id = run.get("id")
            if run_id is None:
                continue
            if _run_is_in_progress(run):
                _tracked_active_run_ids.add(run_id)
            elif run_id in _tracked_active_run_ids:
                _tracked_active_run_ids.discard(run_id)
                completed_events.append((repo_key, run))
    return runs_by_repo, completed_events


def _notify_completed(repo_key, run):
    """Show a desktop notification for a run that just finished."""
    success = run.get("conclusion") == "success"
    emoji = "🟢" if success else "🔴"
    result = "succeeded" if success else "failed"
    name = run.get("name") or "Workflow"
    branch = (run.get("head_branch") or "—").strip()
    head = run.get("head_commit") or {}
    raw_commit = (head.get("message") or "").strip().split("\n")[0][:60].strip() or "—"
    commit_msg = raw_commit.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    duration = format_duration(run.get("run_started_at"), run.get("updated_at")) or "—"
    body = f"\r\n<b>{emoji} {name} {result}</b>\r\n      {branch}\r\n      {commit_msg}\r\n      Duration: {duration}"
    notify.notify(title=repo_key, body=body, url=run.get("html_url"))
