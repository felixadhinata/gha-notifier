"""Polling logic: fetch watches status (default 5s) and refresh branch list (default 30s)."""

import threading
from gi.repository import GLib

import store
from branch_service import refresh_watch_status
from helper import log


WATCH_STATUS_POLL_INTERVAL_SEC = 5
BRANCH_LIST_POLL_INTERVAL_SEC = 30
# Cap in-progress fetches per poll so main-thread chunk updates stay bounded
MAX_IN_PROGRESS_FETCH_PER_POLL = 40


class PollerManager:
    """Runs two workers: fetch watches status and refresh branch list. Uses store for config, client, and callbacks."""

    def __init__(self):
        self.watch_status_source_id = None
        self.branch_list_poll_source_id = None
        self.is_polling = False

    def start_polling(self):
        if self.watch_status_source_id:
            GLib.source_remove(self.watch_status_source_id)
            self.watch_status_source_id = None
        if self.branch_list_poll_source_id:
            GLib.source_remove(self.branch_list_poll_source_id)
            self.branch_list_poll_source_id = None
        interval = max(5, int(store.config.get("pollIntervalSec", WATCH_STATUS_POLL_INTERVAL_SEC)))
        self.watch_status_source_id = GLib.timeout_add_seconds(interval, self.poll_once)
        branch_interval = max(5, int(store.config.get("branchListPollIntervalSec", BRANCH_LIST_POLL_INTERVAL_SEC)))
        self.branch_list_poll_source_id = GLib.timeout_add_seconds(
            branch_interval, self.branch_list_poll_once
        )

    def poll_once(self):
        """Build in-progress list on main thread, then fetch in worker. Returns True to keep the timeout active."""
        if self.is_polling:
            return True
        fetch_list = _in_progress_watch_keys_from_store()
        if not fetch_list:
            return True
        log(f"poll: watch status — fetching {len(fetch_list)} in-progress watch(es)")
        self.is_polling = True
        threading.Thread(target=self._poll_worker, args=(fetch_list,), daemon=True).start()
        return True

    def _poll_worker(self, fetch_list):
        """Fetch watches status in background. fetch_list was built on main thread."""
        def on_done():
            self.is_polling = False
            log("poll: watch status — done")
        refresh_watch_status(
            store.client,
            fetch_list=fetch_list,
            on_done=on_done,
        )

    def branch_list_poll_once(self):
        """Refresh branch list (default 30s). Returns True to keep the timeout active."""
        if store.refresh_branch_list_poll:
            log("poll: branch list — refreshing")
            store.refresh_branch_list_poll()
        return True


def _in_progress_watch_keys_from_store():
    """On main thread: return list of (repo_key, branch, run_id) for rows to refresh. run_id is the run we're watching (0 if unknown)."""
    out = []
    if not store.watches_list_store:
        return out
    n = store.watches_list_store.get_n_items()
    for i in range(n):
        if len(out) >= MAX_IN_PROGRESS_FETCH_PER_POLL:
            break
        row = store.watches_list_store.get_item(i)
        repo_key = getattr(row, "repo_key", "") or ""
        if "/" not in repo_key:
            continue
        status = (getattr(row, "status", None) or "").strip().lower()
        if status and status not in ("yellow", "gray"):
            continue
        branch = getattr(row, "branch", "") or ""
        run_id = int(getattr(row, "run_id", 0) or 0)
        out.append((repo_key, branch, run_id))
    return out
