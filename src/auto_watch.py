"""Shared logic for applying branch auto-watch rules (used by pollers and branches_workflows tab)."""

from config import find_watch, get_all_watches, save_config


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------

def apply_auto_watches(config, repo_key, branch_name, runs, on_changed=None):
    """Add workflows matching branch auto-watch patterns to config['autoWatches']. If branch has no branchAutoWatch, create it with enabled=True. Calls on_changed() if config changed."""
    key = f"{repo_key}:{branch_name}"
    branch_auto = (config.get("branchAutoWatch") or {}).get(key)
    config_created = not branch_auto
    if not branch_auto:
        _ensure_auto_watch_config(config, repo_key, branch_name)
        branch_auto = config.get("branchAutoWatch", {}).get(key, {})
    if not branch_auto.get("enabled"):
        return
    raw = (branch_auto.get("patterns") or "").strip()
    patterns = [p.strip().lower() for p in raw.split(",") if p.strip()]
    if not patterns:
        return
    all_watches = get_all_watches(config) + list(config.get("autoWatches") or [])
    auto_watches = config.get("autoWatches", [])
    if not isinstance(auto_watches, list):
        auto_watches = []
    changed = False
    for run in runs:
        name = (run.get("name") or "").lower()
        head = run.get("head_commit") or {}
        commit_msg = (head.get("message") or "").lower()
        if not any(p in name for p in patterns) and not any(p in commit_msg for p in patterns):
            continue
        wf_id = int(run.get("workflow_id") or 0)
        if wf_id == 0:
            continue
        run_id = int(run.get("id") or 0)
        if run_id and find_watch(all_watches, repo_key, branch_name, run_id):
            continue
        auto_watches.append(
            {
                "repo": repo_key,
                "branch": branch_name,
                "runId": run_id,
            }
        )
        changed = True
    if changed or config_created:
        config["autoWatches"] = auto_watches
        save_config(config)
        if on_changed:
            on_changed()


# ---------------------------------------------------------------------------
# Private
# ---------------------------------------------------------------------------

def _ensure_auto_watch_config(config, repo_key, branch_name):
    """If branch has no branchAutoWatch entry, create it with enabled=True. Returns the settings dict."""
    key = f"{repo_key}:{branch_name}"
    branch_auto = config.get("branchAutoWatch") or {}
    if not isinstance(branch_auto, dict):
        config["branchAutoWatch"] = {}
        branch_auto = {}
    if key not in branch_auto:
        branch_auto[key] = {"enabled": True, "patterns": ""}
        config["branchAutoWatch"] = branch_auto
    return config["branchAutoWatch"][key]
