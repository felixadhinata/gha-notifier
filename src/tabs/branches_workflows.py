"""Branches & Workflows tab: branch list and workflow runs table. Uses branch_service for data."""

import os
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gio, GLib, Gtk, Pango

from config import find_watch, find_watch_repo_branch, get_all_watches, get_repos, save_config, set_repos
from branch_service import _refresh_watches_fetch, refresh_branch_list
from dialogs import ManageBranchesDialog, WorkflowBranchSettingsDialog
from formatters import format_duration, format_run_started_at, status_color_from_run
from models import WorkflowRunRow
import store
from table_helpers import add_column, make_open_url_factory, make_status_factory, text_factory
from ui_helpers import clear_box, run_dialog_modal

from auto_watch import apply_auto_watches

from .watches import refresh_watches_tab

# Loading-state key for full branch refresh (spinner on Branches section)
BRANCH_REFRESH_LOADING_KEY = "__refresh__"

# Local cache for workflow runs in this tab (replaces store.run_cache).
_runs_cache = {}


def refresh_branches():
    """Refresh branch data in background; store update and post-update UI run on main thread. branch_service runs refresh_watches when apply finishes."""
    filter_q = (store.branch_filter_entry.get_text() or "").strip().lower()
    refresh_branch_list(
        store.config,
        store.client,
        store.pr_to_branch,
        store.pr_branches_loading,
        filter_q,
        on_fetch_done=_after_pr_fetch,
        apply_on_main=True,
    )
    GLib.idle_add(_after_refresh_branches)


def _after_refresh_branches():
    """Run on main thread after refresh_branches: clear loading, refill list UI, refresh workflows."""
    store.pr_branches_loading.discard(BRANCH_REFRESH_LOADING_KEY)
    update_branches_header_loading()
    refill_branch_list()
    refresh_workflows_for_selection()


def refresh_branch_list_from_poll():
    """Called by pollers every 30s: refresh branch list (with API) in a thread, then refill UI on main thread."""
    filter_q = ""
    if getattr(store, "branch_filter_entry", None) and store.branch_filter_entry:
        filter_q = (store.branch_filter_entry.get_text() or "").strip().lower()

    def _run():
        refresh_branch_list(
            store.config,
            store.client,
            store.pr_to_branch,
            store.pr_branches_loading,
            filter_q,
            on_fetch_done=_after_pr_fetch,
            apply_on_main=True,
        )

    threading.Thread(target=_run, daemon=True).start()


def refresh_watch_workflows(on_after_refresh=None):
    """Run watch fetch in background; fill store and optional on_after_refresh on main thread (never blocks UI)."""
    def worker():
        effective_watches, runs_by_key = _refresh_watches_fetch(store.config, store.client)

        def on_main():
            from tabs.watches import fill_watches_store
            fill_watches_store(effective_watches, runs_by_key)
            if on_after_refresh:
                on_after_refresh()

        GLib.idle_add(on_main)

    threading.Thread(target=worker, daemon=True).start()


def toggle_watch(repo, branch, workflow_id, run_id, active):
    """Add or remove a watch in config['watches'] only. Watches are keyed by runId (the run we're watching)."""
    watches = store.config.get("watches", [])
    if not isinstance(watches, list):
        watches = []
    run_id_int = int(run_id or 0)
    existing_exact = find_watch(watches, repo, branch, run_id_int)
    existing_any = find_watch_repo_branch(watches, repo, branch)
    if active:
        existing = existing_exact or existing_any
        if not existing:
            watches.append(
                {
                    "repo": repo,
                    "branch": branch,
                    "runId": run_id_int,
                }
            )
            store.config["watches"] = watches
        elif existing and run_id_int:
            existing["runId"] = run_id_int
    else:
        to_remove = existing_exact or existing_any
        if to_remove and to_remove in watches:
            watches = [w for w in watches if w is not to_remove]
            store.config["watches"] = watches
    save_config(store.config)
    store.update_tray_menu()


def _on_refresh_branches():
    """Refresh branch store in a background thread; show loading spinner on branches section until done."""
    _runs_cache.clear()
    store.pr_branches_loading.add(BRANCH_REFRESH_LOADING_KEY)
    update_branches_header_loading()
    threading.Thread(target=refresh_branches, daemon=True).start()


def _on_refresh_workflows():
    """Reload workflow runs for the selected branch. Used by the Workflows refresh button."""
    if store.selected_branch is None:
        return
    repo_key, branch_name = store.selected_branch
    _runs_cache.pop(f"{repo_key}:{branch_name}", None)
    refresh_workflows_for_selection()


def _on_workflows_settings_clicked():
    """Open workflow auto-watch settings for the selected branch. Used by the Workflows settings button."""
    if store.selected_branch is None:
        return
    repo_key, branch_name = store.selected_branch
    dialog = WorkflowBranchSettingsDialog(store.window, repo_key, branch_name)
    response = run_dialog_modal(dialog)
    if response == Gtk.ResponseType.OK:
        dialog.apply()
    dialog.destroy()
    refresh_workflows_for_selection()


def _on_manage_branches():
    """Open manage branches dialog. Used by the Add/Delete branch button."""
    if not store.client or not store.client.token:
        return
    dialog = ManageBranchesDialog(store.window)
    response = run_dialog_modal(dialog)
    if response == Gtk.ResponseType.OK:
        dialog.apply_selection()
        for r in get_repos(store.config):
            if r.auto_add_pr_branches:
                store.pr_to_branch.pop(r.repo_key, None)
        render_branches_list()
        store.update_tray_menu()
    dialog.destroy()


def fetch_runs(owner, repo, branch):
    """Load workflow runs for a branch (from cache or API). Used by refresh_workflows_for_selection."""
    key = f"{owner}/{repo}:{branch}"
    if key in _runs_cache:
        return _runs_cache[key]
    if not store.client.token:
        return []
    try:
        runs = store.client.get_runs(owner, repo, branch).get("workflow_runs", [])
    except Exception:
        return []
    _runs_cache[key] = runs
    return runs


def update_branches_header_loading():
    """Show/hide branches section spinner based on store.pr_branches_loading."""
    if store.pr_branches_loading:
        store.branches_section_spinner.set_visible(True)
        store.branches_section_spinner.start()
    else:
        store.branches_section_spinner.stop()
        store.branches_section_spinner.set_visible(False)


def update_workflows_header_loading():
    """Show/hide workflows section spinner based on store._workflows_loading_count."""
    if store._workflows_loading_count > 0:
        store.workflows_section_spinner.set_visible(True)
        store.workflows_section_spinner.start()
    else:
        store.workflows_section_spinner.stop()
        store.workflows_section_spinner.set_visible(False)


def _after_pr_fetch(repo_key):
    """Run on main thread after PR branches fetch: clear loading and re-render branch list."""
    store.pr_branches_loading.discard(repo_key)
    render_branches_list()


def render_branches_list():
    """Rebuild store.branch_list from branch_service (no API refresh); start PR fetch for auto-add repos if needed."""
    filter_q = (store.branch_filter_entry.get_text() or "").strip().lower()
    refresh_branch_list(
        store.config,
        None,
        store.pr_to_branch,
        store.pr_branches_loading,
        filter_q,
        on_fetch_done=_after_pr_fetch,
    )
    update_branches_header_loading()
    refill_branch_list()
    refresh_workflows_for_selection()


def _on_branch_row_activated(listbox, row):
    """Handle branch list row activation: set selected branch and refresh workflows panel."""
    if row is None or not store.branch_list:
        return
    idx = row.get_index()
    if idx < 0 or idx >= len(store.branch_list):
        return
    _display, repo_key, branch_name = store.branch_list[idx]
    if not branch_name:
        listbox.unselect_row(row)
        return
    store.selected_branch = (repo_key, branch_name)
    refresh_workflows_for_selection()


def _workflows_show_placeholder():
    """Show 'Select a branch' placeholder in workflows panel."""
    lbl = Gtk.Label()
    lbl.set_markup("<b>Workflows</b>")
    store.workflows_header_content.append(lbl)
    placeholder = Gtk.Label(label="Select a branch above to see workflow runs.")
    placeholder.set_halign(Gtk.Align.CENTER)
    placeholder.set_valign(Gtk.Align.CENTER)
    placeholder.set_hexpand(True)
    placeholder.set_vexpand(True)
    center = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    center.set_hexpand(True)
    center.set_vexpand(True)
    center.append(placeholder)
    store.workflows_container.append(center)


def _workflows_show_loading(repo_key, branch_name):
    """Show workflows header (branch + optional PR link) and loading state. Returns (owner, repo) for fetch."""
    sel = f"{repo_key} — {branch_name}".replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    lbl = Gtk.Label()
    lbl.set_markup(f"<b>Workflows</b> ({sel}")
    store.workflows_header_content.append(lbl)
    repo_ptb = store.pr_to_branch.get(repo_key) or {}
    pr_num = next((n for n, b in repo_ptb.items() if b == branch_name), None)
    if pr_num:
        link = Gtk.LinkButton(uri=f"https://github.com/{repo_key}/pull/{pr_num}", label=f" #{pr_num}")
        link.set_halign(Gtk.Align.START)
        store.workflows_header_content.append(link)
    store.workflows_header_content.append(Gtk.Label(label=")"))
    loading_lbl = Gtk.Label(label="Loading…")
    loading_lbl.set_halign(Gtk.Align.CENTER)
    loading_lbl.set_valign(Gtk.Align.CENTER)
    loading_lbl.set_hexpand(True)
    loading_lbl.set_vexpand(True)
    loading_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    loading_box.set_hexpand(True)
    loading_box.set_vexpand(True)
    loading_box.append(loading_lbl)
    store.workflows_container.append(loading_box)
    store._workflows_loading_count += 1
    GLib.idle_add(update_workflows_header_loading)
    return repo_key.split("/", 1)


def _workflows_show_result(repo_key, branch_name, runs):
    """On main thread: replace loading with empty message or workflow table."""
    store._workflows_loading_count = max(0, store._workflows_loading_count - 1)
    update_workflows_header_loading()
    clear_box(store.workflows_container)
    if not runs:
        empty = Gtk.Label(label="No workflow runs found.")
        empty.set_xalign(0)
        store.workflows_container.append(empty)
    else:
        apply_auto_watches(store.config, repo_key, branch_name, runs, on_changed=store.update_tray_menu)
        grid = build_workflows_table(repo_key, branch_name, runs, get_all_watches(store.config))
        store.workflows_container.append(grid)
        grid.set_hexpand(True)
        grid.set_vexpand(True)


def refresh_workflows_for_selection():
    """Update the workflows panel for the current branch selection (placeholder or load runs)."""
    clear_box(store.workflows_container)
    enabled = store.selected_branch is not None
    store.workflows_refresh_btn.set_sensitive(enabled)
    store.workflows_settings_btn.set_sensitive(enabled)
    clear_box(store.workflows_header_content)
    if store.selected_branch is None:
        _workflows_show_placeholder()
        return
    repo_key, branch_name = store.selected_branch
    owner, repo = _workflows_show_loading(repo_key, branch_name)

    def worker():
        runs = fetch_runs(owner, repo, branch_name)
        GLib.idle_add(lambda: _workflows_show_result(repo_key, branch_name, runs))

    threading.Thread(target=worker, daemon=True).start()


def build_branches_workflows_tab():
    """Build the 'Branches & Workflows' tab content. Sets widget refs on store."""
    tab1_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)

    # --- Branches section ---
    branches_inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    branches_inner.set_margin_start(12)
    branches_inner.set_margin_end(12)
    branches_inner.set_margin_top(4)
    branches_inner.set_margin_bottom(8)
    branches_header_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    store.branches_section_label = Gtk.Label()
    store.branches_section_label.set_markup("<b>Branches</b>")
    store.branches_section_label.set_halign(Gtk.Align.START)
    store.branches_section_spinner = Gtk.Spinner()
    spacer = Gtk.Box()
    spacer.set_hexpand(True)
    branches_header_row.append(store.branches_section_label)
    branches_header_row.append(store.branches_section_spinner)
    branches_header_row.append(spacer)
    manage_btn = Gtk.Button(label="Add / Delete branch")
    manage_btn.connect("clicked", lambda *a: _on_manage_branches())
    refresh_btn = Gtk.Button()
    refresh_btn.set_child(Gtk.Image.new_from_icon_name("view-refresh-symbolic"))
    refresh_btn.set_tooltip_text("Refresh")
    refresh_btn.connect("clicked", lambda *a: _on_refresh_branches())
    branches_header_row.append(refresh_btn)
    branches_header_row.append(manage_btn)
    branches_inner.append(branches_header_row)

    store.branch_filter_entry = Gtk.SearchEntry(placeholder_text="Filter branches…")
    store.branch_filter_entry.connect("search-changed", lambda e: render_branches_list())
    branches_inner.append(store.branch_filter_entry)

    store.branch_listbox = Gtk.ListBox()
    store.branch_listbox.set_size_request(-1, 320)
    store.branch_listbox.add_css_class("navigation-sidebar")
    store.branch_listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
    store.branch_listbox.connect(
        "row-activated",
        lambda lb, r: _on_branch_row_activated(lb, r),
    )
    store._branch_listbox_scroll = Gtk.ScrolledWindow()
    store._branch_listbox_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    store._branch_listbox_scroll.set_child(store.branch_listbox)
    store._branch_listbox_scroll.set_vexpand(True)
    branch_list_frame = Gtk.Frame()
    branch_list_frame.set_child(store._branch_listbox_scroll)
    branch_list_frame.set_vexpand(True)
    branches_inner.append(branch_list_frame)
    tab1_box.append(branches_inner)
    branches_inner.set_hexpand(True)
    branches_inner.set_vexpand(True)

    # --- Workflows section ---
    workflows_inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    workflows_inner.set_margin_start(12)
    workflows_inner.set_margin_end(12)
    workflows_inner.set_margin_top(4)
    workflows_inner.set_margin_bottom(8)
    workflows_header_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    store.workflows_header_content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
    store.workflows_header_content.append(Gtk.Label())
    store.workflows_section_spinner = Gtk.Spinner()
    spacer2 = Gtk.Box()
    spacer2.set_hexpand(True)
    workflows_header_row.append(store.workflows_header_content)
    workflows_header_row.append(store.workflows_section_spinner)
    workflows_header_row.append(spacer2)
    store.workflows_refresh_btn = Gtk.Button()
    store.workflows_refresh_btn.set_child(Gtk.Image.new_from_icon_name("view-refresh-symbolic"))
    store.workflows_refresh_btn.set_tooltip_text("Refresh workflows")
    store.workflows_refresh_btn.connect("clicked", lambda *a: _on_refresh_workflows())
    store.workflows_refresh_btn.set_sensitive(False)
    workflows_header_row.append(store.workflows_refresh_btn)
    store.workflows_settings_btn = Gtk.Button()
    store.workflows_settings_btn.set_child(Gtk.Image.new_from_icon_name("preferences-other-symbolic"))
    store.workflows_settings_btn.set_tooltip_text("Workflow settings for this branch")
    store.workflows_settings_btn.connect("clicked", lambda *a: _on_workflows_settings_clicked())
    store.workflows_settings_btn.set_sensitive(False)
    workflows_header_row.append(store.workflows_settings_btn)
    workflows_inner.append(workflows_header_row)

    store.workflows_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    scroll_workflows = Gtk.ScrolledWindow()
    scroll_workflows.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
    scroll_workflows.set_min_content_height(180)
    scroll_workflows.set_child(store.workflows_container)
    scroll_workflows.set_vexpand(True)
    workflow_table_frame = Gtk.Frame()
    workflow_table_frame.set_child(scroll_workflows)
    workflow_table_frame.set_vexpand(True)
    workflows_inner.append(workflow_table_frame)
    tab1_box.append(workflows_inner)
    workflows_inner.set_hexpand(True)
    workflows_inner.set_vexpand(True)

    store.branches_section_spinner.set_visible(False)
    store.workflows_section_spinner.set_visible(False)
    return tab1_box


def refill_branch_list():
    """Refill the branch ListBox from store.branch_list; group headers are not selectable."""
    new_listbox = Gtk.ListBox()
    new_listbox.set_size_request(-1, 320)
    new_listbox.add_css_class("navigation-sidebar")
    new_listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
    new_listbox.connect(
        "row-activated",
        lambda lb, r: _on_branch_row_activated(lb, r),
    )
    for display, repo_key, branch_name in store.branch_list:
        row = Gtk.ListBoxRow()
        is_header = not bool(branch_name)
        lbl = Gtk.Label()
        lbl.set_xalign(0)
        lbl.set_ellipsize(Pango.EllipsizeMode.END)
        lbl.set_margin_start(8)
        lbl.set_margin_end(8)
        lbl.set_margin_top(4)
        lbl.set_margin_bottom(4)
        if is_header:
            lbl.set_markup(f"<b>{display or repo_key}</b>")
            lbl.add_css_class("branch-group-header")
        else:
            lbl.set_label(display)
        row.set_child(lbl)
        new_listbox.append(row)
    store._branch_listbox_scroll.set_child(new_listbox)
    store.branch_listbox = new_listbox
    if store.selected_branch:
        repo_key, branch_name = store.selected_branch
        for i, (_, r, b) in enumerate(store.branch_list):
            if r == repo_key and b == branch_name:
                store.branch_listbox.select_row(store.branch_listbox.get_row_at_index(i))
                break


def _run_to_workflow_row(repo_key, branch_name, run, watches):
    """Build a WorkflowRunRow from a run dict and watches list."""
    name = run.get("name", "Workflow")
    status = run.get("status", "")
    conclusion = run.get("conclusion") or ""
    in_progress = (status or "").lower() in ("in_progress", "queued")
    duration = format_duration(run.get("run_started_at"), None if in_progress else run.get("updated_at"))
    head_commit = run.get("head_commit") or {}
    commit_msg = (head_commit.get("message") or "").strip().split("\n")[0][:60] or "—"
    author = (run.get("actor") or {}).get("login") or "—"
    triggered = format_run_started_at(run.get("run_started_at"))
    run_wf_id = int(run.get("workflow_id") or 0)
    run_id = int(run.get("id") or 0)
    is_watched = bool(find_watch(watches, repo_key, branch_name, run_id))
    url = run.get("html_url") or ""
    return WorkflowRunRow(
        name, status, conclusion, duration, commit_msg, author,
        triggered, is_watched, url, run_wf_id, run_id,
    )


def build_workflows_table(repo_key, branch_name, runs, watches):
    """Build the workflow runs ColumnView for the given runs and watches. Returns the column_view widget."""
    run_store = Gio.ListStore.new(WorkflowRunRow)
    for run in runs:
        run_store.append(_run_to_workflow_row(repo_key, branch_name, run, watches))

    selection = Gtk.NoSelection.new(run_store)
    column_view = Gtk.ColumnView(model=selection)
    column_view.set_hexpand(False)
    column_view.set_size_request(950, -1)
    column_view.set_show_column_separators(True)

    _watch_hids = {}

    def make_watch_factory():
        factory = Gtk.SignalListItemFactory()
        def setup(_f, i):
            center_box = Gtk.CenterBox()
            center_box.set_hexpand(True)
            cb = Gtk.CheckButton()
            center_box.set_center_widget(cb)
            i.set_child(center_box)
        def bind(_f, i):
            o = i.get_item()
            center_box = i.get_child()
            cb = center_box.get_center_widget() if center_box else None
            if o and cb:
                hid = _watch_hids.pop(id(cb), None)
                if hid is not None:
                    cb.disconnect(hid)
                cb.set_active(o.watch)
                hid = cb.connect("toggled", _make_watch_toggled(o, cb))
                _watch_hids[id(cb)] = hid
        def unbind(_f, i):
            center_box = i.get_child()
            cb = center_box.get_center_widget() if center_box else None
            if cb:
                _watch_hids.pop(id(cb), None)
        factory.connect("setup", setup)
        factory.connect("bind", bind)
        factory.connect("unbind", unbind)
        return factory

    def _make_watch_toggled(row, cb):
        def toggled(btn):
            row.watch = cb.get_active()
            toggle_watch(
                repo_key, branch_name,
                int(row.workflow_id or 0), int(row.run_id or 0),
                cb.get_active(),
            )
        return toggled

    add_column(column_view, "Watch", make_watch_factory(), min_width=60)
    add_column(column_view, "Workflow", text_factory("name"))
    add_column(
        column_view,
        "Status",
        make_status_factory(
            lambda obj: status_color_from_run(obj.status or "", obj.conclusion or "")
        ),
    )
    add_column(column_view, "Duration", text_factory("duration"))
    add_column(column_view, "Commit", text_factory("commit_msg"), expand=True, min_width=300)
    add_column(column_view, "Author", text_factory("author"))
    add_column(column_view, "Triggered", text_factory("triggered"), min_width=150)
    add_column(column_view, "Open", make_open_url_factory())
    return column_view
