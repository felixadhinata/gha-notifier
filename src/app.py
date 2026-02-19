import os
import subprocess
import sys
import threading
import traceback
import webbrowser

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib, Gtk

from config import DEFAULT_CONFIG, get_all_watches, load_config, save_config, set_open_on_startup
from dialogs import RepoDialog, SettingsDialog, TokenLoginDialog
from formatters import get_watch_run_info
from github import GitHubClient
from pollers import PollerManager
from icons import show_fatal_error
import store
from store import register as store_register
from tabs import (
    build_branches_workflows_tab,
    build_watches_tab,
    clear_completed_watches,
    refill_branch_list,
    refresh_watches_tab,
    refresh_workflows_for_selection,
    render_branches_list,
)
from tabs.watches import sync_watches_tab_ui
from tray import TrayHandler, make_command_callback
from ui_helpers import clear_box, run_dialog_modal


APP_ID = "com.gha.notifier"
APP_NAME = "GHA Notifier"
DEBUG = os.environ.get("GHA_NOTIFIER_DEBUG", "").lower() in ("1", "true", "yes")

# When True, app was started with --tray-only (e.g. from autostart); don't show window on activate
START_TRAY_ONLY = "--tray-only" in sys.argv

class GhaNotifierApp(Gtk.Application):
    def __init__(self):
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )
        self.connect("startup", self._on_startup)
        self.connect("shutdown", self._on_shutdown)
        self.config = load_config()
        self.client = GitHubClient(self.config.get("token"))
        self.window = None
        self.tray = None
        from store import (
            pr_to_branch,
            pr_branches_loading,
            branch_list,
        )
        self._pr_to_branch = pr_to_branch
        self._pr_branches_loading = pr_branches_loading
        self._workflows_loading_count = 0
        self._branch_list = branch_list
        self.poll_manager = PollerManager()

    def _on_startup(self, app):
        Gtk.Application.do_startup(self)
        # For Gio.Notification click-to-open when notify uses Gio path
        open_url_act = Gio.SimpleAction.new("open-url", GLib.VariantType("s"))
        open_url_act.connect("activate", lambda _a, p: webbrowser.open(p.get_string(0)))
        self.add_action(open_url_act)

    def get_autostart_exec_command(self):
        """Return the Exec= line for the autostart .desktop file (open on startup). Uses --tray-only so only tray is shown at login."""
        app_py = os.path.abspath(os.path.join(os.path.dirname(__file__), "app.py"))
        return f"{sys.executable} {app_py} --tray-only"

    def do_activate(self):
        try:
            self._do_activate()
        except Exception as e:
            tb = traceback.format_exc()
            sys.stderr.write(tb)
            self._show_error_dialog(f"{type(e).__name__}: {e}\n\n{tb}")

    def _show_error_dialog(self, message):
        parent = self.window if self.window else None
        if parent is None:
            parent = Gtk.Window()
            parent.set_skip_taskbar_hint(True)
            parent.set_decorated(False)
            parent.set_opacity(0)
            parent.set_default_size(1, 1)
        dialog = Gtk.Dialog(transient_for=parent, modal=True, title="GHA Notifier – Error")
        dialog.add_button("Close", Gtk.ResponseType.CLOSE)
        area = dialog.get_content_area()
        area.set_margin_start(18)
        area.set_margin_end(18)
        area.set_margin_top(18)
        area.set_spacing(12)
        primary = Gtk.Label(label="GHA Notifier – Error")
        primary.set_xalign(0)
        primary.set_wrap(True)
        primary.set_selectable(True)
        secondary = Gtk.Label(label=message)
        secondary.set_xalign(0)
        secondary.set_wrap(True)
        secondary.set_selectable(True)
        area.append(primary)
        area.append(secondary)
        dialog.connect("response", lambda d, r: d.destroy())
        dialog.present()

    def _do_activate(self):
        if DEBUG:
            sys.stderr.write("[GHA Notifier] Activating...\n")
        if not self.window:
            self.window = Gtk.ApplicationWindow(application=self)
            self.window.set_title(APP_NAME)
            self.window.set_icon_name("gha-notifier")
            self.window.set_default_size(680, 520)
            self.window.set_size_request(200, 260)
            self.window.connect("close-request", self.on_window_close)
            self.window.connect("map", lambda w: GLib.idle_add(self.refresh_auth_ui))
            store_register(self)
            set_open_on_startup(
                self.config.get("openOnStartup", False),
                self.get_autostart_exec_command(),
            )
            self.build_ui()
            from tabs.branches_workflows import refresh_branch_list_from_poll
            store.refresh_branch_list_poll = refresh_branch_list_from_poll
            if DEBUG:
                sys.stderr.write("[GHA Notifier] UI built.\n")

        self.setup_indicator()
        if DEBUG:
            sys.stderr.write("[GHA Notifier] Ready. Use the Menu button for watches & actions.\n")
        self.ensure_user()
        self.poll_manager.start_polling()
        if store.refresh_branch_list_poll:
            store.refresh_branch_list_poll()

        if not START_TRAY_ONLY:
            self.window.present()
        self.refresh_auth_ui()
        if DEBUG:
            sys.stderr.write("[GHA Notifier] Window shown.\n" if not START_TRAY_ONLY else "[GHA Notifier] Started tray-only.\n")

    def on_window_close(self, *args):
        self.window.set_visible(False)
        return True  # suppress default close (hide instead of destroy)

    def build_ui(self):
        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        container.set_margin_start(16)
        container.set_margin_end(16)
        container.set_margin_top(16)
        container.set_size_request(200, 100)
        self.window.set_child(container)

        self.auth_label = Gtk.Label(label="Sign in to get started")
        self.auth_label.set_xalign(0)

        self.login_hint = Gtk.Label(label="Sign in with GitHub CLI or a Personal Access Token.")
        self.login_hint.set_xalign(0)
        self.login_hint.set_wrap(True)
        self.login_hint.set_margin_bottom(4)

        self.gh_btn = Gtk.Button(label="Sign in with GitHub CLI (gh)")
        self.gh_btn.connect("clicked", self.on_login_with_gh)

        self.token_btn = Gtk.Button(label="Sign in with token")
        self.token_btn.connect("clicked", self.on_login_with_token)

        self.menu_btn = Gtk.MenuButton()
        try:
            self.menu_btn.set_child(Gtk.Image.new_from_icon_name("open-menu-symbolic"))
        except Exception:
            self.menu_btn.set_child(Gtk.Label(label="Menu"))
        self.menu_btn.set_tooltip_text("Settings & account")
        settings_act = Gio.SimpleAction.new("settings", None)
        settings_act.connect("activate", lambda a, v: self.on_settings_clicked())
        self.add_action(settings_act)
        signout_act = Gio.SimpleAction.new("signout", None)
        signout_act.connect("activate", lambda a, v: self.on_logout_clicked())
        self.add_action(signout_act)
        account_menu = Gio.Menu.new()
        account_menu.append("Settings", "app.settings")
        account_menu.append("Sign out", "app.signout")
        self.menu_btn.set_popover(Gtk.PopoverMenu(menu_model=account_menu))

        auth_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        auth_row.append(self.auth_label)
        self.auth_label.set_hexpand(True)
        auth_row.append(self.menu_btn)

        auth_btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        auth_btn_box.append(self.gh_btn)
        auth_btn_box.append(self.token_btn)

        self.status_label = Gtk.Label()
        self.status_label.set_xalign(0)
        self.status_label.set_wrap(True)

        self.login_spinner = Gtk.Spinner()
        self.status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.status_box.append(self.login_spinner)
        self.status_box.append(self.status_label)
        self.status_label.set_hexpand(True)

        container.append(auth_row)
        container.append(self.login_hint)
        self.branches_frame = self.build_branches_and_workflows_sections()
        container.append(self.branches_frame)
        container.append(auth_btn_box)
        container.append(self.status_box)

        render_branches_list()
        self.refresh_auth_ui()

    def build_branches_and_workflows_sections(self):
        notebook = Gtk.Notebook()
        notebook.append_page(build_branches_workflows_tab(), Gtk.Label(label="Branches & Workflows"))
        notebook.append_page(build_watches_tab(), Gtk.Label(label="Watches"))
        notebook.connect("switch-page", self._on_notebook_switch_page)
        return notebook

    def _on_notebook_switch_page(self, notebook, page, page_num):
        """When switching to Watches tab (page 1), refresh once in background. Throttled to avoid repeated emissions."""
        if page_num != 1:
            return
        now = getattr(self, "_last_watches_tab_refresh", 0) or 0
        import time
        if time.time() - now < 2.0:
            return
        self._last_watches_tab_refresh = time.time()
        from tabs.branches_workflows import refresh_watch_workflows
        refresh_watch_workflows(on_after_refresh=sync_watches_tab_ui)

    def refresh_auth_ui(self):
        branches_frame = self.branches_frame
        user = self.config.get("user")
        if user:
            login = (user.get("login") or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            self.auth_label.set_markup(f"Signed in as <b>{login}</b>")
            self.auth_label.set_visible(True)
            self.login_hint.set_visible(False)
            self.gh_btn.set_visible(False)
            self.token_btn.set_visible(False)
            self.menu_btn.set_visible(True)
            branches_frame.set_visible(True)
            self.window.set_default_size(980, 800)
        else:
            self.auth_label.set_text("Sign in to get started")
            self.auth_label.set_visible(True)
            self.login_hint.set_visible(True)
            self.gh_btn.set_visible(True)
            self.token_btn.set_visible(True)
            self.menu_btn.set_visible(True)
            branches_frame.set_visible(False)
            self.window.set_default_size(380, 160)

    def on_settings_clicked(self, *args):
        dialog = SettingsDialog(self.window, app=self)
        response = run_dialog_modal(dialog)
        if response == Gtk.ResponseType.OK:
            dialog.apply()
        dialog.destroy()
        if response == Gtk.ResponseType.OK:
            self.refresh_auth_ui()
            render_branches_list()
            refresh_watches_tab()

    def _set_login_loading(self, loading):
        if loading:
            self.login_spinner.set_visible(True)
            self.login_spinner.start()
            self.gh_btn.set_sensitive(False)
            self.token_btn.set_sensitive(False)
        else:
            self.login_spinner.stop()
            self.login_spinner.set_visible(False)
            self.gh_btn.set_sensitive(True)
            self.token_btn.set_sensitive(True)

    def on_login_with_token(self, *args):
        dialog = TokenLoginDialog(self.window)
        response = run_dialog_modal(dialog)
        token = dialog.get_token() if response == Gtk.ResponseType.OK else None
        dialog.destroy()
        if not token:
            return
        self.status_label.set_text("Checking token…")
        self._set_login_loading(True)
        self._login_with_token(token)

    def on_login_with_gh(self, *args):
        self.status_label.set_text("Getting token from gh…")
        self._set_login_loading(True)
        threading.Thread(target=self._fetch_gh_token, daemon=True).start()

    def _fetch_gh_token(self):
        try:
            result = subprocess.run(
                ["gh", "auth", "token"],
                capture_output=True,
                text=True,
                timeout=10,
                stdin=subprocess.DEVNULL,
            )
            token = (result.stdout or "").strip() if result.returncode == 0 else None
        except Exception:
            token = None
        GLib.idle_add(self._on_gh_token_ready, token)

    def _on_gh_token_ready(self, token):
        if not token:
            self._set_login_loading(False)
            self.status_label.set_text("Could not get token from gh. Install it (e.g. apt install gh) and run: gh auth login")
            return
        self.status_label.set_text("Checking token…")
        threading.Thread(target=self._validate_token_and_login, args=(token,), daemon=True).start()

    def _validate_token_and_login(self, token):
        try:
            client = GitHubClient(token)
            user = client.get_current_user()
        except Exception as exc:
            GLib.idle_add(self._on_login_done, None, str(exc))
            return
        GLib.idle_add(self._on_login_done, (client, token, user), None)

    def _on_login_done(self, result, error_msg):
        self._set_login_loading(False)
        if error_msg:
            self.status_label.set_text(f"Sign-in failed: {error_msg}")
            return
        client, token, user = result
        self.client = client
        self.config["token"] = token
        self.config["user"] = {"login": user.get("login"), "id": user.get("id")}
        save_config(self.config)
        store_register(self)  # so store.client and store.config are current
        self.status_label.set_text("")
        self.refresh_auth_ui()
        self.poll_manager.start_polling()

    def _login_with_token(self, token):
        self.status_label.set_text("Checking token…")
        threading.Thread(target=self._validate_token_and_login, args=(token,), daemon=True).start()

    def on_logout_clicked(self, *args):
        """Sign out: reset config to defaults, clear all stores, refresh UI."""
        self.config = DEFAULT_CONFIG.copy()
        save_config(self.config)
        self.client = GitHubClient(self.config.get("token"))
        self._pr_to_branch.clear()
        self._pr_branches_loading.clear()
        self._branch_list.clear()
        if store.watches_list_store is not None:
            store.watches_list_store.remove_all()
        self.poll_manager.start_polling()
        self.status_label.set_text("")
        self.refresh_auth_ui()
        self.tray.rebuild_menu()
        render_branches_list()
        refresh_watches_tab()

    def refresh_watch_workflows_cb(self):
        """Called by store.refresh_watch_workflows(). Runs fetch in background, fill + tray update on main (never blocks UI)."""
        import threading
        from branch_service import _refresh_watches_fetch

        def worker():
            effective_watches, runs_by_key = _refresh_watches_fetch()

            def on_main():
                from tabs.watches import fill_watches_store
                fill_watches_store(effective_watches, runs_by_key)
                self.tray.rebuild_menu()

            GLib.idle_add(on_main)

        threading.Thread(target=worker, daemon=True).start()


    def ensure_user(self):
        if self.client.token and not self.config.get("user"):
            user = self.client.get_current_user()
            self.config["user"] = {"login": user.get("login"), "id": user.get("id")}
            save_config(self.config)

    def _on_shutdown(self, app):
        if self.tray is not None:
            self.tray.shutdown()

    def setup_indicator(self):
        if self.tray is not None:
            return
        self.tray = TrayHandler()
        assets = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets"))
        on_cmd = make_command_callback(
            self.poll_manager.poll_once,
            lambda: (self.tray.shutdown(), self.quit()),
            clear_completed=clear_completed_watches,
        )
        self.tray.setup(
            on_command=on_cmd,
            assets_path=assets,
            get_menu_payload=self._build_tray_menu_payload,
        )

    def _build_tray_menu_payload(self):
        """Build tray menu payload. Watch = (label, status, url, commit); commit shown as submenu item."""
        from tray import tray_menu_payload
        lst = store.watches_list_store
        if lst is None:
            return tray_menu_payload([])
        by_repo = {}
        n = lst.get_n_items()
        for i in range(n):
            row = lst.get_item(i)
            repo = (row.repo or "").strip()
            by_repo.setdefault(repo, []).append(row)
        entries = []
        for repo in sorted(by_repo.keys()):
            entries.append(("repo", (repo,)))
            for row in by_repo[repo]:
                branch = (row.branch or "—").strip()
                label = f"{row.workflow_name or 'Workflow'} · {branch} · {row.duration or '—'}"
                status = row.status if row.status and row.status != "—" else "gray"
                commit = (row.commit_msg or "—").strip().replace("\n", " ")
                entries.append(("watch", (label, status, row.url or "", commit)))
        return tray_menu_payload(entries)

    def update_tray_menu(self, force=False):
        """Rebuild and send tray menu. When force=True, always call rebuild; otherwise no-op if tray not set up."""
        if self.tray is None and not force:
            return
        if self.tray is not None:
            self.tray.rebuild_menu()


def main():
    if START_TRAY_ONLY:
        sys.argv = [a for a in sys.argv if a != "--tray-only"]
    try:
        app = GhaNotifierApp()
        app.run(sys.argv)
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as e:
        tb = traceback.format_exc()
        sys.stderr.write(tb)
        show_fatal_error(f"{type(e).__name__}: {e}\n\n{tb}")
        sys.exit(1)


if __name__ == "__main__":
    main()
