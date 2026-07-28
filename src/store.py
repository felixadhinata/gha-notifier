"""
Centralized in-memory stores and app callbacks. Import from store; no module imports app.
App registers itself once so store has config, client, window, and callbacks.
"""

__all__ = [
    "repo_runs",
    "config",
    "client",
    "window",
    "update_tray_menu",
    "start_polling",
    "register",
]

# ---------------------------------------------------------------------------
# Shared data: repo_key ("owner/repo") -> list of recent workflow run dicts
# triggered by the signed-in user, most recent first.
# ---------------------------------------------------------------------------
repo_runs = {}

# ---------------------------------------------------------------------------
# App-wide state — set by app via register()
# ---------------------------------------------------------------------------
config = None
client = None
window = None

# ---------------------------------------------------------------------------
# App callbacks — set by app via register(); called by other modules
# ---------------------------------------------------------------------------
update_tray_menu = None
start_polling = None


def register(app):
    """Called once by app: set config, client, window and callbacks. Other modules never import app."""
    global config, client, window, update_tray_menu, start_polling
    config = app.config
    client = app.client
    window = app.window
    update_tray_menu = app.update_tray_menu
    start_polling = app.poll_manager.start_polling
