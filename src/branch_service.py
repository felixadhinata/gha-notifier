"""
Branch and PR data layer: fetch branches, PRs, and in-progress watches.
Updates store.watches_list_store on main thread via GLib.idle_add.
"""
import threading

from gi.repository import Gio, GLib

from config import find_watch, get_all_watches, get_repos, save_config
from formatters import format_duration, format_run_started_at, resolve_status
import notify

def _run_is_in_progress(run):
    return (run.get("status") or "").lower() in ("in_progress", "queued")


def fetch_pr_branches_for_repo(client, login, owner, repo_name, branch_to_pr, pr_to_branch):
    """Fetch open PR branches for one repo. Returns (branch_to_pr, pr_to_branch)."""
    branch_to_pr = dict(branch_to_pr)
    pr_to_branch = dict(pr_to_branch)
    try:
        q = f"repo:{owner}/{repo_name} type:pr author:{login} is:open"
        page = 1
        while True:
            result = client.search_issues(q, page=page, per_page=100)
            items = result.get("items") or []
            for item in items:
                pr_num = item.get("number")
                if not pr_num:
                    continue
                branch_name = pr_to_branch.get(pr_num)
                if not branch_name:
                    try:
                        pr = client.get_pull(owner, repo_name, pr_num)
                        branch_name = (pr.get("head") or {}).get("ref")
                    except Exception:
                        continue
                    if branch_name:
                        pr_to_branch[pr_num] = branch_name
                if branch_name:
                    branch_to_pr[branch_name] = {"pr_number": pr_num, "issue_id": item.get("id")}
            if len(items) < 100:
                break
            page += 1
    except Exception:
        pass
    return branch_to_pr, pr_to_branch


def fetch_pr_branches_worker(repo_key, on_done=None):
    """Load PR branch names for one repo in a background thread. Reads config/client/pr_to_branch from store."""
    import store

    def finish():
        if on_done:
            on_done()

    if not store.client or not store.config:
        finish()
        return
    parts = repo_key.split("/", 1)
    if len(parts) != 2:
        finish()
        return
    owner, repo_name = parts[0], parts[1]
    login = (store.config.get("user") or {}).get("login")
    if not login or not store.client.token:
        finish()
        return
    repo_ptb = dict((store.pr_to_branch or {}).get(repo_key) or {})
    branch_to_pr = {b: {"pr_number": n} for n, b in repo_ptb.items()}
    branch_to_pr, repo_ptb = fetch_pr_branches_for_repo(
        store.client, login, owner, repo_name, branch_to_pr, repo_ptb
    )
    store.pr_to_branch[repo_key] = repo_ptb
    finish()


def _branch_list_data(config, pr_to_branch):
    """Yield (repo_key, combined_branches_set, pr_map) from config and pr_to_branch. pr_map is branch -> {pr_number} for display."""
    ptb = pr_to_branch or {}
    for repo in get_repos(config):
        repo_key = repo.repo_key
        config_branches = set(repo.branches)
        repo_ptb = ptb.get(repo_key) or {}
        combined = config_branches | set(repo_ptb.values())
        pr_map = {b: {"pr_number": n} for n, b in repo_ptb.items()}
        yield repo_key, combined, pr_map


def _refresh_watches_after_branch_list():
    """Run in background: fetch watches then fill store on main thread. Call after branch list apply finishes."""
    from tabs.watches import fill_watches_store

    def worker():
        effective_watches, runs_by_key = _refresh_watches_fetch()
        GLib.idle_add(lambda ef=effective_watches, rbk=runs_by_key: fill_watches_store(ef, rbk))

    threading.Thread(target=worker, daemon=True).start()


def _pr_fetch_done_cb(repo_key, on_fetch_done):
    """Callback for one repo's PR fetch: schedule on_fetch_done on main thread."""
    return (lambda: GLib.idle_add(on_fetch_done, repo_key)) if on_fetch_done else None


def _apply_branch_list_result(rows, ptb, new_auto_watches, repos_to_fetch, on_fetch_done=None):
    """Run on main thread: apply branch list and config, start PR fetch workers, then refresh watches."""
    import store
    store.pr_to_branch.clear()
    store.pr_to_branch.update(ptb)
    store.branch_list.clear()
    store.branch_list.extend(rows)
    store.config["autoWatches"] = new_auto_watches
    threading.Thread(target=lambda: save_config(store.config), daemon=True).start()
    for repo_key in repos_to_fetch:
        store.pr_branches_loading.add(repo_key)
        threading.Thread(
            target=fetch_pr_branches_worker,
            args=(repo_key, _pr_fetch_done_cb(repo_key, on_fetch_done)),
            daemon=True,
        ).start()
    _refresh_watches_after_branch_list()


def _refresh_ptb_for_auto_add(config, client, ptb):
    """Update ptb with PR branch data for repos that have auto_add_pr_branches. Returns (ptb, new_auto_watches)."""
    login = (config.get("user") or {}).get("login")
    if not login:
        return ptb, list(config.get("autoWatches") or [])
    repos = get_repos(config)
    for repo in repos:
        if not repo.auto_add_pr_branches:
            continue
        repo_ptb = dict(ptb.get(repo.repo_key) or {})
        branch_to_pr = {b: {"pr_number": n} for n, b in repo_ptb.items()}
        _, repo_ptb = fetch_pr_branches_for_repo(
            client, login, repo.owner, repo.repo, branch_to_pr, repo_ptb
        )
        ptb[repo.repo_key] = repo_ptb
    valid_pairs = set()
    for repo in repos:
        config_branches = set(repo.branches)
        pr_branches = set((ptb.get(repo.repo_key) or {}).values())
        valid_pairs |= {(repo.repo_key, b) for b in config_branches | pr_branches}
    auto_watches = config.get("autoWatches") or []
    new_auto_watches = [w for w in auto_watches if (w.get("repo"), w.get("branch")) in valid_pairs] if isinstance(auto_watches, list) else []
    return ptb, new_auto_watches


def _build_branch_rows(config, ptb, pr_branches_loading, filter_q):
    """Build (rows, new_auto_watches, repos_to_fetch) from config and ptb."""
    loading_repos = (pr_branches_loading or set())
    repos_to_fetch = []
    for repo_key, combined, pr_map in _branch_list_data(config, ptb):
        repo_entry = next((r for r in get_repos(config) if r.repo_key == repo_key), None)
        if repo_entry and repo_entry.auto_add_pr_branches and repo_key not in ptb and repo_key not in loading_repos:
            repos_to_fetch.append(repo_key)
    loading_repos = loading_repos | set(repos_to_fetch)

    rows = []
    filter_lower = (filter_q or "").strip().lower()
    for repo_key, combined, pr_map in _branch_list_data(config, ptb):
        branches = sorted(combined)
        if not branches and repo_key not in loading_repos:
            continue
        filtered = [b for b in branches if not filter_lower or filter_lower in b.lower()]
        if filtered or repo_key in loading_repos:
            rows.append((repo_key, repo_key, ""))
        for branch_name in filtered:
            pr_num = pr_map.get(branch_name)
            pr_num = pr_num.get("pr_number") if isinstance(pr_num, dict) else pr_num
            display = f"    {repo_key} — {branch_name}" + (f" #{pr_num}" if pr_num else "")
            rows.append((display, repo_key, branch_name))
        if repo_key in loading_repos:
            rows.append((f"    {repo_key} — Loading PR branches…", repo_key, ""))

    valid_in_store = {(r[1], r[2]) for r in rows if r[2]}
    auto_watches = config.get("autoWatches") or []
    if not isinstance(auto_watches, list):
        auto_watches = []
    new_auto_watches = [w for w in auto_watches if (w.get("repo"), w.get("branch")) in valid_in_store]
    config_pairs = {(w.get("repo"), w.get("branch")) for w in new_auto_watches}
    for repo_key, branch_name in valid_in_store:
        if (repo_key, branch_name) not in config_pairs:
            new_auto_watches.append({"repo": repo_key, "branch": branch_name, "runId": 0})
            config_pairs.add((repo_key, branch_name))
    return rows, new_auto_watches, repos_to_fetch


def refresh_branch_list(filter_q, on_fetch_done=None, apply_on_main=False):
    """
    Refresh PR data for auto-add repos, build branch list, update store.
    Reads config, client, pr_to_branch, pr_branches_loading from store.
    When apply_on_main=True schedules apply on main thread (call from a background thread);
    when False applies immediately (call from main thread, no API calls made).
    """
    import store
    ptb = dict(store.pr_to_branch) if store.pr_to_branch is not None else {}
    if apply_on_main and store.client and store.client.token:
        ptb, new_auto_pruned = _refresh_ptb_for_auto_add(store.config, store.client, ptb)
        if new_auto_pruned != (store.config.get("autoWatches") or []):
            store.config["autoWatches"] = new_auto_pruned

    rows, new_auto_watches, repos_to_fetch = _build_branch_rows(store.config, ptb, store.pr_branches_loading, filter_q)

    if apply_on_main:
        GLib.idle_add(lambda: _apply_branch_list_result(rows, ptb, new_auto_watches, repos_to_fetch, on_fetch_done))
        return

    # Sync path: main thread, no API calls, apply immediately
    store.branch_list.clear()
    store.branch_list.extend(rows)
    store.pr_to_branch.clear()
    store.pr_to_branch.update(ptb)
    store.config["autoWatches"] = new_auto_watches
    save_config(store.config)
    for repo_key in repos_to_fetch:
        store.pr_branches_loading.add(repo_key)
        threading.Thread(
            target=fetch_pr_branches_worker,
            args=(repo_key, _pr_fetch_done_cb(repo_key, on_fetch_done)),
            daemon=True,
        ).start()


def _fetch_run_by_id(client, repo_key, run_id):
    """Fetch one run by id. Returns (run_id, run) or (None, None)."""
    if "/" not in repo_key or run_id <= 0:
        return None, None
    owner, repo = repo_key.split("/", 1)
    try:
        run = client.get_run(owner, repo, run_id)
        return (run_id, run) if run and run.get("id") else (None, None)
    except Exception:
        return None, None


def refresh_watch_status(fetch_list=None, on_done=None):
    """Fetch each run by run_id, then update store rows on main thread. Call from a background thread."""
    import store
    run_by_id = {}
    if not store.client or not store.client.token:
        GLib.idle_add(lambda: _update_watch_status(run_by_id, on_done))
        return
    if not fetch_list:
        if on_done:
            GLib.idle_add(on_done)
        return
    for item in fetch_list:
        repo_key = item[0] if item else ""
        run_id = int(item[2] or 0) if len(item) >= 3 else 0
        rid, run = _fetch_run_by_id(store.client, repo_key, run_id)
        if rid is not None:
            run_by_id[rid] = run
    GLib.idle_add(lambda rbi=run_by_id, od=on_done: _update_watch_status(rbi, od))


def _refresh_watches_fetch():
    """
    Build effective watch list and fetch runs (API). Safe to run in a background thread.
    Reads config and client from store.
    Returns (effective_watches, runs_by_key). Caller must run fill_watches_store on main thread.
    Enriches runs_by_key with each watch's run (by id) so completed runs get correct status when table is refilled.
    """
    import store
    if not store.client or not store.client.token:
        return [], {}
    targets = _auto_watch_targets(store.config)
    runs_by_key = _fetch_auto_watch_runs(store.config, store.client, targets)
    base_watches = get_all_watches(store.config)
    effective_watches = list(base_watches)

    effective_keys = {_watch_key(w) for w in effective_watches}
    if store.watches_list_store is not None:
        n = store.watches_list_store.get_n_items()
        for i in range(n):
            row = store.watches_list_store.get_item(i)
            w = _watch_row_to_dict(row)
            if _watch_key(w) in effective_keys:
                continue
            effective_keys.add(_watch_key(w))
            effective_watches.append(w)

    for key, runs in runs_by_key.items():
        if ":" not in key:
            continue
        repo_key, branch_name = key.rsplit(":", 1)
        for run in runs:
            run_id = int(run.get("id") or 0)
            if run_id == 0:
                continue
            w = {"repo": repo_key, "branch": branch_name, "runId": run_id}
            if _watch_key(w) in effective_keys:
                continue
            effective_keys.add(_watch_key(w))
            effective_watches.append(w)

    for watch in effective_watches:
        key = f"{watch.get('repo') or ''}:{watch.get('branch') or ''}"
        run_id = int(watch.get("runId") or 0)
        if run_id <= 0:
            continue
        runs = runs_by_key.get(key, [])
        if any(int(r.get("id") or 0) == run_id for r in runs):
            continue
        _rid, run = _fetch_run_by_id(store.client, watch.get("repo") or "", run_id)
        if run:
            runs_by_key.setdefault(key, []).append(run)
    return effective_watches, runs_by_key


def refresh_watches():
    """
    Build effective watch list and fill store.watches_list_store. Call from main thread only,
    or use _refresh_watches_fetch in a thread + fill_watches_store on main.
    """
    from tabs.watches import fill_watches_store

    effective_watches, runs_by_key = _refresh_watches_fetch()
    fill_watches_store(effective_watches, runs_by_key)


# ---------------------------------------------------------------------------
# Private
# ---------------------------------------------------------------------------

def _auto_watch_targets(config):
    """Return list of (owner, repo_name, repo_key, branch_name, patterns) for branches with auto-watch enabled and patterns set."""
    branch_auto = config.get("branchAutoWatch") or {}
    if not isinstance(branch_auto, dict):
        return []
    targets = []
    for key, settings in branch_auto.items():
        if not settings.get("enabled"):
            continue
        raw = (settings.get("patterns") or "").strip()
        patterns = [p.strip().lower() for p in raw.split(",") if p.strip()]
        parts = key.rsplit(":", 1)
        if len(parts) != 2:
            continue
        repo_key, branch_name = parts[0], parts[1]
        repo_parts = repo_key.split("/", 1)
        if len(repo_parts) != 2:
            continue
        owner, repo_name = repo_parts[0], repo_parts[1]
        targets.append((owner, repo_name, repo_key, branch_name, patterns))
    return targets


def _run_matches_patterns(run, patterns):
    """True if run name or head commit message contains any pattern (substring, case-insensitive). Same logic as auto_watch.apply_auto_watches."""
    if not patterns:
        return False
    name = (run.get("name") or "").lower()
    head = run.get("head_commit") or {}
    commit_msg = (head.get("message") or "").lower()
    return any(p in name for p in patterns) or any(p in commit_msg for p in patterns)


def _fetch_auto_watch_runs(config, client, targets):
    """Fetch in-progress runs for auto-watch targets. Filters by branch patterns (workflow name / commit message). Returns runs_by_key."""
    runs_by_key = {}
    branch_auto_watch = config.get("branchAutoWatch") or {}
    for owner, repo_name, repo_key, branch_name, patterns in targets:
        key = f"{repo_key}:{branch_name}"
        settings = branch_auto_watch.get(key) if isinstance(branch_auto_watch, dict) else {}
        if not settings.get("enabled"):
            continue
        try:
            runs = client.get_runs(owner, repo_name, branch_name, status="in_progress").get("workflow_runs", [])
        except Exception:
            runs = []
        if patterns:
            runs = [r for r in runs if _run_matches_patterns(r, patterns)]
        runs_by_key[key] = runs
    return runs_by_key

_notified_run_ids = set()


def _notify_completed(row, run):
    """Show a desktop notification when a watched run completes (once per run per session). Includes emoji status and commit message."""
    run_id = run.get("id")
    if run_id in _notified_run_ids:
        return
    _notified_run_ids.add(run_id)
    success = run.get("conclusion") == "success"
    emoji = "🟢" if success else "🔴"
    result = "succeeded" if success else "failed"
    name = run.get("name") or "Workflow"
    head = run.get("head_commit") or {}
    raw_commit = (head.get("message") or "").strip().split("\n")[0][:60].strip() or "—"
    commit_msg = raw_commit.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    duration = format_duration(run.get("run_started_at"), run.get("updated_at")) or "—"
    body = f"\r\n<b>{emoji} {name} {result}</b>\r\n      {commit_msg}\r\n      Duration: {duration}"
    notify.notify(title=f"{row.repo} / {row.branch}", body=body, url=run.get("html_url"))


def _apply_run_to_row(row, run):
    """Update one watch row from run data. Returns status for indicator."""
    previous_status = row.status
    status = resolve_status(run)
    row.status = status
    row.duration = format_duration(run.get("run_started_at"), None if _run_is_in_progress(run) else run.get("updated_at")) or "—"
    row.url = run.get("html_url", "") or ""
    head = run.get("head_commit") or {}
    row.commit_msg = (head.get("message") or "").strip().split("\n")[0][:60] or "—"
    row.author = (run.get("actor") or {}).get("login") or "—"
    row.triggered = format_run_started_at(run.get("run_started_at")) or "—"
    row.workflow_name = run.get("name") or "Workflow"
    if previous_status == "yellow" and row.status in ("green", "red"):
        _notify_completed(row, run)

def _update_watch_status(run_by_id, on_done=None):
    """Run on main thread: update each store row from run_by_id by row.run_id, then refresh tray menu file."""
    import store
    if store.watches_list_store is None:
        if on_done:
            on_done()
        return
    n = store.watches_list_store.get_n_items()
    for i in range(n):
        row = store.watches_list_store.get_item(i)
        run_id = int(row.run_id or 0)
        run = run_by_id.get(run_id) if run_id else None
        if run:
            _apply_run_to_row(row, run)
    if getattr(store, "update_tray_menu", None):
        store.update_tray_menu(force=True)
    if on_done:
        on_done()


def _watch_key(watch):
    """(repo, branch, runId) for dedup. Accepts dict or WatchRow."""
    if hasattr(watch, "get") and callable(getattr(watch, "get")):
        return (watch.get("repo") or "", watch.get("branch") or "", int(watch.get("runId") or 0))
    # WatchRow
    repo = getattr(watch, "repo_key", None) or getattr(watch, "repo", None) or ""
    branch = getattr(watch, "branch", None) or ""
    run_id = int(getattr(watch, "run_id", None) or 0)
    return (repo, branch, run_id)


def _watch_row_to_dict(row):
    """Convert WatchRow to watch dict (repo, branch, runId)."""
    return {
        "repo": getattr(row, "repo_key", None) or getattr(row, "repo", None) or "",
        "branch": getattr(row, "branch", None) or "",
        "runId": int(getattr(row, "run_id", None) or 0),
    }
