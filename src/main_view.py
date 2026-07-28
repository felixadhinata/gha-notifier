"""Main view: monitored-repo list on the left, that repo's recent runs (triggered by you) on the right."""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gio, GLib, Gtk, Pango

from config import add_repo, get_repos, remove_repo, save_config
from dialogs import AddRepoDialog
from formatters import STATUS_COLORS, format_duration, format_run_started_at, status_color_from_run
from models import RunRow
from repo_service import refresh_repo_runs, repo_status_from_runs
import store
from table_helpers import add_column, make_open_url_factory, make_status_factory, text_factory
from ui_helpers import clear_box, run_dialog_modal


class _UI:
    """Holds widget refs owned by this view."""
    repos_listbox = None
    repos_scroll = None
    repos_spinner = None
    add_repo_btn = None
    runs_header_label = None
    runs_refresh_btn = None
    runs_container = None
    selected_repo = None


_ui = _UI()


def build_main_view():
    """Build the repos | runs split view. Returns the outer widget."""
    paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
    paned.set_wide_handle(True)
    paned.set_position(260)
    paned.set_resize_start_child(False)
    paned.set_shrink_start_child(False)
    paned.set_resize_end_child(True)
    paned.set_shrink_end_child(False)

    paned.set_start_child(_build_repos_pane())
    paned.set_end_child(_build_runs_pane())

    render_repos_pane()
    _render_runs_pane()
    return paned


def render_repos_pane():
    """Rebuild the repos ListBox from store.config['repos'] + store.repo_runs statuses."""
    listbox = Gtk.ListBox()
    listbox.add_css_class("navigation-sidebar")
    listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
    listbox.connect("row-activated", _on_repo_row_activated)

    for repo_key in get_repos(store.config) if store.config else []:
        row = Gtk.ListBoxRow()
        row.repo_key = repo_key
        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        content.set_margin_start(8)
        content.set_margin_end(4)
        content.set_margin_top(6)
        content.set_margin_bottom(6)

        dot = Gtk.Label()
        dot.set_markup(_dot_markup(repo_status_from_runs(store.repo_runs.get(repo_key))))

        name_lbl = Gtk.Label(label=repo_key)
        name_lbl.set_xalign(0)
        name_lbl.set_hexpand(True)
        name_lbl.set_ellipsize(Pango.EllipsizeMode.END)

        remove_btn = Gtk.Button()
        remove_btn.set_child(Gtk.Image.new_from_icon_name("list-remove-symbolic"))
        remove_btn.add_css_class("flat")
        remove_btn.set_tooltip_text("Stop monitoring this repository")
        remove_btn.connect("clicked", lambda _b, rk=repo_key: _on_remove_repo_clicked(rk))

        content.append(dot)
        content.append(name_lbl)
        content.append(remove_btn)
        row.set_child(content)
        listbox.append(row)

        if _ui.selected_repo == repo_key:
            listbox.select_row(row)

    _ui.repos_scroll.set_child(listbox)
    _ui.repos_listbox = listbox


def reset_selection():
    """Clear the selected repo (e.g. on sign-out) and refresh the runs pane to the empty state."""
    _ui.selected_repo = None
    _render_runs_pane()


def on_repo_runs_updated():
    """Called after store.repo_runs is refreshed (periodic poll or manual refresh). Safe on main thread only."""
    render_repos_pane()
    _render_runs_pane()


# ---------------------------------------------------------------------------
# Private: building blocks
# ---------------------------------------------------------------------------

def _dot_markup(status):
    color = STATUS_COLORS.get(status or "gray", STATUS_COLORS["gray"])
    return f"<span foreground='{color}'>●</span>"


def _build_repos_pane():
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    box.set_margin_start(12)
    box.set_margin_end(8)
    box.set_margin_top(4)
    box.set_margin_bottom(8)
    box.set_size_request(220, -1)

    header_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    label = Gtk.Label()
    label.set_markup("<b>Monitored repos</b>")
    label.set_halign(Gtk.Align.START)
    label.set_hexpand(True)
    _ui.repos_spinner = Gtk.Spinner()
    _ui.repos_spinner.set_visible(False)
    header_row.append(label)
    header_row.append(_ui.repos_spinner)
    box.append(header_row)

    _ui.repos_listbox = Gtk.ListBox()
    _ui.repos_scroll = Gtk.ScrolledWindow()
    _ui.repos_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    _ui.repos_scroll.set_child(_ui.repos_listbox)
    _ui.repos_scroll.set_vexpand(True)
    frame = Gtk.Frame()
    frame.set_child(_ui.repos_scroll)
    frame.set_vexpand(True)
    box.append(frame)

    _ui.add_repo_btn = Gtk.Button(label="+ Add repository")
    _ui.add_repo_btn.connect("clicked", lambda *a: _on_add_repo_clicked())
    box.append(_ui.add_repo_btn)
    return box


def _build_runs_pane():
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    box.set_margin_start(8)
    box.set_margin_end(12)
    box.set_margin_top(4)
    box.set_margin_bottom(8)
    box.set_hexpand(True)

    header_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    _ui.runs_header_label = Gtk.Label()
    _ui.runs_header_label.set_halign(Gtk.Align.START)
    _ui.runs_header_label.set_hexpand(True)
    _ui.runs_header_label.set_ellipsize(Pango.EllipsizeMode.END)
    _ui.runs_refresh_btn = Gtk.Button()
    _ui.runs_refresh_btn.set_child(Gtk.Image.new_from_icon_name("view-refresh-symbolic"))
    _ui.runs_refresh_btn.set_tooltip_text("Refresh")
    _ui.runs_refresh_btn.connect("clicked", lambda *a: _on_refresh_clicked())
    _ui.runs_refresh_btn.set_sensitive(False)
    header_row.append(_ui.runs_header_label)
    header_row.append(_ui.runs_refresh_btn)
    box.append(header_row)

    _ui.runs_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    scroll = Gtk.ScrolledWindow()
    scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
    scroll.set_min_content_height(180)
    scroll.set_child(_ui.runs_container)
    scroll.set_vexpand(True)
    frame = Gtk.Frame()
    frame.set_child(scroll)
    frame.set_vexpand(True)
    box.append(frame)
    return box


def _centered(widget):
    widget.set_halign(Gtk.Align.CENTER)
    widget.set_valign(Gtk.Align.CENTER)
    widget.set_hexpand(True)
    widget.set_vexpand(True)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    box.set_hexpand(True)
    box.set_vexpand(True)
    box.append(widget)
    return box


def _render_runs_pane():
    clear_box(_ui.runs_container)
    _ui.runs_refresh_btn.set_sensitive(_ui.selected_repo is not None)
    if _ui.selected_repo is None:
        _ui.runs_header_label.set_text("")
        placeholder = Gtk.Label(label="Select a repository to see your recent workflow runs.")
        _ui.runs_container.append(_centered(placeholder))
        return

    repo_key = _ui.selected_repo
    _ui.runs_header_label.set_markup(
        f"<b>{GLib.markup_escape_text(repo_key)}</b>  —  your runs, all branches"
    )
    runs = store.repo_runs.get(repo_key)
    if runs is None:
        _ui.runs_container.append(_centered(Gtk.Label(label="Loading…")))
        return
    if not runs:
        empty = Gtk.Label(label="No workflow runs found for you in this repository.")
        empty.set_xalign(0)
        _ui.runs_container.append(empty)
        return

    table = _build_runs_table(runs)
    table.set_hexpand(True)
    table.set_vexpand(True)
    _ui.runs_container.append(table)


def _build_runs_table(runs):
    run_store = Gio.ListStore.new(RunRow)
    for run in runs:
        run_store.append(_run_to_row(run))
    selection = Gtk.NoSelection.new(run_store)
    column_view = Gtk.ColumnView(model=selection)
    column_view.set_hexpand(True)
    column_view.set_show_column_separators(True)

    add_column(column_view, "Workflow", text_factory("name"), min_width=140)
    add_column(column_view, "Branch", text_factory("branch"), min_width=160)
    add_column(
        column_view,
        "Status",
        make_status_factory(lambda obj: status_color_from_run(obj.status or "", obj.conclusion or "")),
    )
    add_column(column_view, "Duration", text_factory("duration"))
    add_column(column_view, "Commit", text_factory("commit_msg"), expand=True, min_width=300)
    add_column(column_view, "Author", text_factory("author"))
    add_column(column_view, "Triggered", text_factory("triggered"), min_width=150)
    add_column(column_view, "Open", make_open_url_factory())
    return column_view


def _run_to_row(run):
    name = run.get("name") or "Workflow"
    branch = run.get("head_branch") or "—"
    status = run.get("status") or ""
    conclusion = run.get("conclusion") or ""
    in_progress = (status or "").lower() in ("in_progress", "queued")
    duration = format_duration(run.get("run_started_at"), None if in_progress else run.get("updated_at"))
    head_commit = run.get("head_commit") or {}
    commit_msg = (head_commit.get("message") or "").strip().split("\n")[0][:60] or "—"
    author = (run.get("actor") or {}).get("login") or "—"
    triggered = format_run_started_at(run.get("run_started_at"))
    run_id = int(run.get("id") or 0)
    url = run.get("html_url") or ""
    return RunRow(name, branch, status, conclusion, duration, commit_msg, author, triggered, url, run_id)


# ---------------------------------------------------------------------------
# Private: event handlers
# ---------------------------------------------------------------------------

def _on_repo_row_activated(listbox, row):
    repo_key = getattr(row, "repo_key", None)
    if not repo_key:
        return
    _ui.selected_repo = repo_key
    _render_runs_pane()


def _on_add_repo_clicked():
    if not store.client or not store.client.token:
        return
    dialog = AddRepoDialog(store.window)
    response = run_dialog_modal(dialog)
    repo_key = dialog.get_selected_repo() if response == Gtk.ResponseType.OK else None
    dialog.destroy()
    if not repo_key or not add_repo(store.config, repo_key):
        return
    save_config(store.config)
    render_repos_pane()
    refresh_repo_runs(on_done=lambda _r: on_repo_runs_updated())


def _on_remove_repo_clicked(repo_key):
    if not remove_repo(store.config, repo_key):
        return
    save_config(store.config)
    store.repo_runs.pop(repo_key, None)
    if _ui.selected_repo == repo_key:
        _ui.selected_repo = None
    render_repos_pane()
    _render_runs_pane()
    if store.update_tray_menu:
        store.update_tray_menu(force=True)


def _on_refresh_clicked():
    _set_repos_loading(True)

    def on_done(_runs):
        _set_repos_loading(False)
        on_repo_runs_updated()

    refresh_repo_runs(on_done=on_done)


def _set_repos_loading(loading):
    if loading:
        _ui.repos_spinner.set_visible(True)
        _ui.repos_spinner.start()
    else:
        _ui.repos_spinner.stop()
        _ui.repos_spinner.set_visible(False)
