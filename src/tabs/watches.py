"""Watches tab: list of watches. Table reads from config (watches + autoWatches). Clear completed removes finished runs."""

import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib, Gtk

from config import get_all_watches, save_config
from formatters import format_run_started_at, get_watch_run_info
from store import WatchRow, watches_list_store
from table_helpers import add_column, make_open_url_factory, make_status_factory, text_factory

import store


class _UI:
    """Holds widget refs owned by this tab. Set during build_watches_tab()."""
    watches_section_spinner = None
    watches_section_label = None
    watches_empty_label = None
    watches_table_scroll = None

_ui = _UI()

# Column widths aligned with workflow table in branches_workflows.py


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------

def build_watches_tab():
    """Build the 'Watches' tab content. Sets widget refs on _ui and returns the outer box."""
    store.watches_list_store = Gio.ListStore.new(WatchRow)
    selection = Gtk.NoSelection.new(store.watches_list_store)
    column_view = Gtk.ColumnView(model=selection)
    column_view.set_hexpand(True)
    column_view.set_vexpand(True)
    column_view.set_reorderable(False)
    column_view.set_show_column_separators(True)

    add_column(column_view, "Repo", text_factory("repo"), min_width=140)
    add_column(column_view, "Branch", text_factory("branch"))
    add_column(column_view, "Workflow", text_factory("workflow_name"))
    add_column(column_view, "Status", make_status_factory(lambda obj: (obj.status or "") if obj else ""))
    add_column(column_view, "Duration", text_factory("duration"))
    add_column(column_view, "Commit", text_factory("commit_msg"), expand=True, min_width=300)
    add_column(column_view, "Author", text_factory("author"))
    add_column(column_view, "Triggered", text_factory("triggered"), min_width=150)
    add_column(column_view, "Open", make_open_url_factory())

    # Section header: Watches label, spinner, spacer, Refresh, Clear completed
    header_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    _ui.watches_section_label = Gtk.Label()
    _ui.watches_section_label.set_markup("<b>Watches</b>")
    _ui.watches_section_label.set_halign(Gtk.Align.START)
    _ui.watches_section_spinner = Gtk.Spinner()
    _ui.watches_section_spinner.set_visible(False)
    spacer = Gtk.Box()
    spacer.set_hexpand(True)
    refresh_btn = Gtk.Button()
    try:
        refresh_btn.set_child(Gtk.Image.new_from_icon_name("view-refresh-symbolic"))
    except Exception:
        refresh_btn.set_child(Gtk.Image.new_from_icon_name("view-refresh"))
    refresh_btn.set_tooltip_text("Refresh")
    refresh_btn.connect("clicked", _on_refresh_clicked)
    clear_btn = Gtk.Button(label="Clear completed")
    clear_btn.connect("clicked", _on_clear_completed_clicked)
    header_row.append(_ui.watches_section_label)
    header_row.append(_ui.watches_section_spinner)
    header_row.append(spacer)
    header_row.append(refresh_btn)
    header_row.append(clear_btn)

    scroll = Gtk.ScrolledWindow()
    scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
    scroll.set_min_content_height(180)
    scroll.set_child(column_view)

    outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    outer.set_margin_start(12)
    outer.set_margin_end(12)
    outer.set_margin_top(12)
    outer.set_margin_bottom(12)
    _ui.watches_empty_label = Gtk.Label(
        label="No watches. Use the \"Branches & Workflows\" tab to add watches."
    )
    _ui.watches_empty_label.set_xalign(0)
    _ui.watches_empty_label.set_wrap(True)
    _ui.watches_table_scroll = scroll
    outer.append(header_row)
    outer.append(_ui.watches_empty_label)
    outer.append(scroll)
    scroll.set_vexpand(True)
    seed_watches_from_config()
    return outer


def clear_completed_watches():
    """Remove completed rows from watches_list_store; if a row is in config.watches, remove it there too. Then update_tray_menu."""
    if store.watches_list_store is None:
        if store.update_tray_menu:
            store.update_tray_menu()
        return
    n = store.watches_list_store.get_n_items()
    to_remove_from_config = set()
    for i in range(n - 1, -1, -1):
        row = store.watches_list_store.get_item(i)
        if (row.status or "").strip().lower() not in ("green", "red"):
            continue
        store.watches_list_store.remove(i)
        to_remove_from_config.add((row.repo_key or "", row.branch or "", int(row.run_id or 0)))
    if store.config and to_remove_from_config:
        watches = list(store.config.get("watches", []))
        keep = [w for w in watches if (w.get("repo"), w.get("branch"), int(w.get("runId") or 0)) not in to_remove_from_config]
        if len(keep) < len(watches):
            store.config["watches"] = keep
            save_config(store.config)
    _sync_watches_visibility()
    if store.update_tray_menu:
        store.update_tray_menu()


_FILL_WATCHES_CHUNK_SIZE = 20


def fill_watches_store(watch_list, runs_by_key=None):
    """Populate store.watches_list_store from watch dicts. Chunks appends when large so UI stays responsive."""
    if not watch_list:
        watch_list = []
    if store.watches_list_store is None:
        return
    store.watches_list_store.remove_all()
    if len(watch_list) <= _FILL_WATCHES_CHUNK_SIZE:
        for watch in watch_list:
            store.watches_list_store.append(_watch_to_row(watch, runs_by_key))
        _sync_watches_visibility()
        return
    GLib.idle_add(_fill_watches_store_chunk, watch_list, runs_by_key, 0)


def _fill_watches_store_chunk(watch_list, runs_by_key, start):
    """Append a chunk of watches; schedule next chunk or sync visibility. Run on main thread."""
    end = min(start + _FILL_WATCHES_CHUNK_SIZE, len(watch_list))
    for i in range(start, end):
        store.watches_list_store.append(_watch_to_row(watch_list[i], runs_by_key))
    if end < len(watch_list):
        GLib.idle_add(_fill_watches_store_chunk, watch_list, runs_by_key, end)
    else:
        _sync_watches_visibility()


def _sync_watches_visibility():
    """Update scroll/empty visibility from current list store."""
    if store.watches_list_store is None:
        return
    n = store.watches_list_store.get_n_items()
    if _ui.watches_table_scroll is not None:
        _ui.watches_table_scroll.set_visible(n > 0)
    if _ui.watches_empty_label is not None:
        _ui.watches_empty_label.set_visible(n == 0)


def sync_watches_tab_ui():
    """Update Watches tab visibility (scroll/empty label) from current list store. Safe to call from main thread only."""
    _sync_watches_visibility()


def refresh_watches_tab():
    """Refresh watches from branch_service (config + in-progress), then sync Watches tab UI. Blocks on main thread."""
    from branch_service import refresh_watches
    if store.config and store.client:
        refresh_watches()
    sync_watches_tab_ui()


def seed_watches_from_config():
    """Fill the watches list store from store.config (for initial tab load and after clear_completed). No run data; poll will update status."""
    if not store.config:
        return
    watches = list(get_all_watches(store.config))
    fill_watches_store(watches, None)


# ---------------------------------------------------------------------------
# Private
# ---------------------------------------------------------------------------

def _on_clear_completed_clicked(btn):
    clear_completed_watches()


def _on_refresh_clicked(btn):
    """Refresh: run refresh_watch_workflows in background, then repopulate table. Show loading spinner until done."""
    _set_watches_loading(True)
    def _worker():
        from tabs.branches_workflows import refresh_watch_workflows
        refresh_watch_workflows(on_after_refresh=lambda: _set_watches_loading(False))
    threading.Thread(target=_worker, daemon=True).start()


def _set_watches_loading(loading):
    """Show or hide the Watches section spinner."""
    if not _ui.watches_section_spinner:
        return
    if loading:
        _ui.watches_section_spinner.set_visible(True)
        _ui.watches_section_spinner.start()
    else:
        _ui.watches_section_spinner.stop()
        _ui.watches_section_spinner.set_visible(False)


def _watch_to_row(watch, runs_by_key=None):
    """Build a WatchRow from a watch dict and optional runs_by_key. Watch is keyed by runId."""
    repo = watch.get("repo") or ""
    branch = watch.get("branch") or ""
    run_id = int(watch.get("runId") or 0)
    name, status, duration = get_watch_run_info(watch, runs_by_key)
    key = f"{repo}:{branch}"
    runs = (runs_by_key or {}).get(key, [])
    match = next((r for r in runs if int(r.get("id") or 0) == run_id), None) if run_id else None
    url = match.get("html_url", "") if match else ""
    head_commit = (match.get("head_commit") or {}) if match else {}
    commit_msg = (head_commit.get("message") or "").strip().split("\n")[0][:60] if head_commit else "—"
    if not commit_msg:
        commit_msg = "—"
    actor = (match.get("actor") or {}) if match else {}
    author = actor.get("login") or "—"
    triggered = format_run_started_at(match.get("run_started_at") if match else None) or "—"
    repo_display = repo.split("/", 1)[-1] if "/" in repo else repo
    return WatchRow(
        repo_key=repo,
        repo=repo_display,
        branch=branch,
        workflow_name=name or "Workflow",
        status=status or "—",
        duration=duration or "—",
        commit_msg=commit_msg,
        author=author,
        triggered=triggered,
        url=url,
        run_id=run_id,
    )
