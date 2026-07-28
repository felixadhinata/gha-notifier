"""Polling logic: on an interval, refresh each monitored repo's recent runs triggered by you."""

from gi.repository import GLib

import store
from helper import log
from main_view import on_repo_runs_updated
from repo_service import refresh_repo_runs

DEFAULT_POLL_INTERVAL_SEC = 20


class PollerManager:
    """Refreshes store.repo_runs on an interval. Uses store for config, client, and callbacks."""

    def __init__(self):
        self.source_id = None
        self.is_polling = False

    def start_polling(self):
        if self.source_id:
            GLib.source_remove(self.source_id)
            self.source_id = None
        interval = max(10, int(store.config.get("pollIntervalSec", DEFAULT_POLL_INTERVAL_SEC)))
        self.source_id = GLib.timeout_add_seconds(interval, self.poll_once)

    def poll_once(self):
        """Refresh monitored repos' runs in a background thread. Returns True to keep the timeout active."""
        if self.is_polling:
            return True
        if not store.client or not store.client.token or not store.config.get("repos"):
            return True
        log("poll: refreshing monitored repos")
        self.is_polling = True

        def on_done(_runs_by_repo):
            self.is_polling = False
            on_repo_runs_updated()

        refresh_repo_runs(on_done=on_done)
        return True
