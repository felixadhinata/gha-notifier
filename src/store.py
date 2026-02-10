"""
Centralized in-memory stores and app callbacks. Import from store; no module imports app.
App registers itself once so store has config, client, window, and callbacks.
"""

from models import RepoConfig, WatchRow, WorkflowRunRow

__all__ = [
    "RepoConfig",
    "WatchRow",
    "WorkflowRunRow",
    "pr_to_branch",
    "pr_branches_loading",
    "branch_list",
    "watches_list_store",
    "config",
    "client",
    "window",
    "selected_branch",
    "update_tray_menu",
    "start_polling",
    "refresh_watch_workflows",
    "refresh_branch_list_poll",
    "register",
]

# ---------------------------------------------------------------------------
# In-memory data (keyed by repo_key or "repo_key:branch")
# ---------------------------------------------------------------------------
pr_to_branch = {}
pr_branches_loading = set()
branch_list = []
watches_list_store = None

# Set by app via register()
config = None
client = None
window = None
selected_branch = None
_workflows_loading_count = 0

# Callbacks set by app via register(); other modules call these
update_tray_menu = None
start_polling = None
refresh_watch_workflows = None
refresh_branch_list_poll = None

# UI widget refs (set when tabs are built)
branch_listbox = None
workflows_container = None
_branch_listbox_scroll = None
branch_filter_entry = None
branches_section_spinner = None
workflows_section_spinner = None
workflows_header_content = None
workflows_refresh_btn = None
workflows_settings_btn = None
branches_section_label = None
watches_section_spinner = None
watches_section_label = None
watches_empty_label = None
watches_table_scroll = None


def register(app):
    """Called once by app: set config, client, window and callbacks. Other modules never import app."""
    global config, client, window, update_tray_menu, start_polling, refresh_watch_workflows
    config = app.config
    client = app.client
    window = app.window
    update_tray_menu = app.update_tray_menu
    start_polling = app.poll_manager.start_polling
    refresh_watch_workflows = app.refresh_watch_workflows_cb
