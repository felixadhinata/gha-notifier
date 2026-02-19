"""
System tray: libayatana-appindicator in a subprocess (Gtk 3) + in-window menu.
All tray logic lives here. Requires: gir1.2-ayatanaappindicator3-0.1
"""
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time

import gi
gi.require_version("GLib", "2.0")
from gi.repository import GLib

SOCKET_ENV = "GHA_NOTIFIER_SOCKET"
MENU_FILE_ENV = "GHA_NOTIFIER_MENU_FILE"
ASSETS_ENV = "GHA_NOTIFIER_ASSETS"


def make_command_callback(poll_once, shutdown_and_quit, clear_completed=None):
    """Build the callback for tray menu commands. Run from a bg thread; schedules on main thread via GLib.idle_add."""
    import store

    def handle(cmd):
        def run():
            if cmd == "open":
                store.window.set_visible(True)
                store.window.present()
            elif cmd == "refresh":
                poll_once()
            elif cmd == "clear_completed" and clear_completed:
                clear_completed()
            elif cmd == "quit":
                shutdown_and_quit()
        GLib.idle_add(run)
    return handle


def _server_loop(socket_path, on_command):
    """Accept tray connection and handle commands (open, refresh, quit, etc.)."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        try:
            os.unlink(socket_path)
        except FileNotFoundError:
            pass
        sock.bind(socket_path)
        sock.listen(1)
        while True:
            conn, _ = sock.accept()
            buf = b""
            try:
                while True:
                    data = conn.recv(512)
                    if not data:
                        break
                    buf += data
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        cmd = line.decode("utf-8", errors="replace").strip()
                        if cmd:
                            on_command(cmd)
            except Exception:
                pass
            finally:
                conn.close()
    except (BrokenPipeError, OSError):
        pass
    finally:
        sock.close()
        try:
            os.unlink(socket_path)
        except Exception:
            pass


def _sanitize(s):
    return (s or "").replace("\t", " ").replace("\n", " ").replace("\r", " ").strip()


def tray_menu_payload(data):
    """Encode or decode tray menu. data=list of (kind, args) -> str; data=str -> list of (kind, args)."""
    if isinstance(data, str):
        out = []
        for line in (data or "").strip().split("\n"):
            line = line.strip()
            if not line or line == "end":
                continue
            parts = line.split("\t")
            if parts[0] == "repo" and len(parts) >= 2:
                out.append(("repo", (parts[1],)))
            elif parts[0] == "watch" and len(parts) >= 4:
                commit = parts[4] if len(parts) >= 5 else ""
                out.append(("watch", (parts[1], parts[2], parts[3], commit)))
        return out
    lines = []
    for kind, args in data or []:
        if kind == "repo":
            lines.append("repo\t" + _sanitize(args[0]))
        elif kind == "watch" and len(args) >= 3:
            row = "watch\t" + _sanitize(args[0]) + "\t" + _sanitize(args[1]) + "\t" + _sanitize(args[2])
            if len(args) >= 4:
                row += "\t" + _sanitize(args[3])
            lines.append(row)
    lines.append("end")
    return "\n".join(lines)


_STATUS_EMOJI = {"green": "🟢", "yellow": "🟡", "red": "🔴", "gray": "⚪"}

# Priority: yellow > red > green > gray (same as formatters.pick_status)
_ICON_PRIORITY = ("yellow", "red", "green", "gray")


def _pick_indicator_status(parsed):
    """From parsed menu entries, collect watch statuses and return one with priority yellow > red > green > gray."""
    statuses = set()
    for kind, args in parsed:
        if kind == "watch" and len(args) >= 2:
            s = (args[1] or "gray").lower()
            if s in _ICON_PRIORITY:
                statuses.add(s)
    for p in _ICON_PRIORITY:
        if p in statuses:
            return p
    return "gray"


def _indicator_icon(status, assets_dir):
    """Icon for tray indicator: path to asset icon-{status}.png."""
    s = (status or "gray").lower()
    if s not in _ICON_PRIORITY:
        s = "gray"
    return os.path.join(assets_dir, f"icon-{s}.png")


def _status_label(status, label_text=""):
    """Return label text: status emoji + label (e.g. 🟢 Workflow · 1m)."""
    s = (status or "gray").lower()
    emoji = _STATUS_EMOJI.get(s, _STATUS_EMOJI["gray"])
    return f"{emoji} {label_text or '—'}"


def _open_url(url):
    try:
        import webbrowser
        webbrowser.open(url.strip())
    except Exception:
        pass


def run_indicator():
    """Run the AppIndicator UI (Gtk 3). Call only from the helper subprocess. Reads menu from file every 3s."""
    if not os.environ.get(SOCKET_ENV) or not os.environ.get(MENU_FILE_ENV):
        sys.stderr.write("GHA Notifier: missing GHA_NOTIFIER_SOCKET or GHA_NOTIFIER_MENU_FILE\n")
        sys.exit(1)

    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import Gtk, Gdk, AyatanaAppIndicator3, GLib

    # Zero vertical spacing for menu items
    try:
        style_provider = Gtk.CssProvider()
        style_provider.load_from_data(b"""
            menuitem {
                padding-top: 0px;
                padding-bottom: 0px;
                min-height: 0px;
            }
        """)
        screen = Gdk.Screen.get_default()
        if screen:
            Gtk.StyleContext.add_provider_for_screen(
                screen, style_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
    except Exception:
        pass

    socket_path = os.environ.get(SOCKET_ENV)
    menu_file = os.environ.get(MENU_FILE_ENV)
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect(socket_path)
        sock.settimeout(0)
    except Exception:
        sock = None

    assets = os.environ.get(ASSETS_ENV) or os.path.join(os.path.dirname(__file__), "..", "assets")
    icon_ok = os.path.isfile(os.path.join(assets, "icon-gray.png"))
    if icon_ok:
        ind = AyatanaAppIndicator3.Indicator.new_with_path(
            "gha-notifier", "icon-gray",
            AyatanaAppIndicator3.IndicatorCategory.APPLICATION_STATUS, assets,
        )
    else:
        ind = AyatanaAppIndicator3.Indicator.new(
            "gha-notifier", "indicator-messages",
            AyatanaAppIndicator3.IndicatorCategory.APPLICATION_STATUS,
        )
    ind.set_status(AyatanaAppIndicator3.IndicatorStatus.ACTIVE)
    ind.set_attention_icon("indicator-messages-new")

    menu = Gtk.Menu()
    ind.set_menu(menu)

    def send_cmd(cmd):
        if sock:
            try:
                sock.sendall((cmd + "\n").encode())
            except Exception:
                pass

    def set_item_label(item, text):
        for child in item.get_children():
            if hasattr(child, "set_text"):
                child.set_text(text)
                return
            if hasattr(child, "set_label"):
                child.set_label(text)
                return

    def set_watch_item(header_item, link_item, status, label_text, commit_text=""):
        text = _status_label(status, label_text)
        for c in header_item.get_children():
            if hasattr(c, "set_text"):
                c.set_text(text)
                break
            if hasattr(c, "set_label"):
                c.set_label(text)
                break
        for c in link_item.get_children():
            if hasattr(c, "set_text"):
                c.set_text(f"       {commit_text or '—'}")
                break
            if hasattr(c, "set_label"):
                c.set_label(f"       {commit_text or '—'}")
                break

    last_payload = [None]
    # (structure_signature, list of (repo_item, [(header_item, link_item), ...])) for in-place updates
    _menu_state = [None, []]

    def _repos_structure(repos):
        return [(r[0], len(r[1])) for r in repos if r[0]]

    def build_menu():
        try:
            payload = open(menu_file, "r", encoding="utf-8").read()
        except Exception:
            payload = ""
        parsed = tray_menu_payload(payload)

        repos = []
        current_repo = None
        current_watches = []
        for kind, args in parsed:
            if kind == "repo":
                if current_repo is not None:
                    repos.append((current_repo, current_watches))
                current_repo = args[0] if args else ""
                current_watches = []
            elif kind == "watch":
                current_watches.append(args)
        if current_repo is not None:
            repos.append((current_repo, current_watches))

        new_sig = _repos_structure(repos)
        old_sig, dynamic = _menu_state
        # If structure unchanged, update labels/icon in place so submenus don't collapse.
        if payload == last_payload[0]:
            return True
        if old_sig == new_sig and len(dynamic) == len(new_sig):
            last_payload[0] = payload
            repos_with_name = [(r, w) for r, w in repos if r]
            for (repo_item, watch_pairs), (repo_name, watches) in zip(dynamic, repos_with_name):
                set_item_label(repo_item, repo_name)
                for (header_item, link_item), args in zip(watch_pairs, watches):
                    label = args[0] if len(args) >= 1 else "—"
                    status = args[1] if len(args) >= 2 else "gray"
                    commit = args[3] if len(args) >= 4 else ""
                    set_watch_item(header_item, link_item, status, label, commit)
            try:
                ind.set_icon(_indicator_icon(_pick_indicator_status(parsed), assets))
            except Exception:
                pass
            return True

        last_payload[0] = payload
        menu.foreach(lambda w: menu.remove(w))
        dynamic = []

        for repo_name, watches in repos:
            if not repo_name:
                continue
            repo_item = Gtk.MenuItem(label=repo_name)
            submenu = Gtk.Menu()
            pairs = []
            for args in watches:
                label = args[0] if len(args) >= 1 else "—"
                status = args[1] if len(args) >= 2 else "gray"
                url = args[2] if len(args) >= 3 else ""
                commit = args[3] if len(args) >= 4 else ""

                header_item = Gtk.MenuItem(label=_status_label(status, label))
                try:
                    header_item.get_child().set_ellipsize(3)
                except Exception:
                    pass
                if url and url.strip():
                    header_item.connect("activate", lambda _, u=url: _open_url(u))
                submenu.append(header_item)

                link_item = Gtk.MenuItem(label=f"       {commit or '—'}")
                link_item.set_sensitive(False)
                try:
                    link_item.get_child().set_ellipsize(3)
                except Exception:
                    pass
                submenu.append(link_item)
                pairs.append((header_item, link_item))

            repo_item.set_submenu(submenu)
            menu.append(repo_item)
            dynamic.append((repo_item, pairs))

        _menu_state[0] = new_sig
        _menu_state[1] = dynamic
        if repos:
            menu.append(Gtk.SeparatorMenuItem())
        for label, cmd in [("Open", "open"), ("Refresh", "refresh"), ("Clear completed", "clear_completed")]:
            item = Gtk.MenuItem(label=label)
            item.connect("activate", lambda _, c=cmd: send_cmd(c))
            menu.append(item)
        menu.append(Gtk.SeparatorMenuItem())
        quit_item = Gtk.MenuItem(label="Quit")
        quit_item.connect("activate", lambda _: (send_cmd("quit"), Gtk.main_quit()))
        menu.append(quit_item)
        menu.show_all()
        try:
            ind.set_icon(_indicator_icon(_pick_indicator_status(parsed), assets))
        except Exception:
            pass
        return True

    build_menu()
    GLib.timeout_add_seconds(3, build_menu)
    Gtk.main()


class TrayHandler:
    """Tray subprocess reads menu from a file every 3s. App writes that file on rebuild_menu(). Socket only for tray->app commands (Open, Refresh, Quit)."""

    def __init__(self):
        self._process = None
        self._menu_file = None
        self._get_menu_payload = None

    def setup(self, on_command, assets_path=None, get_menu_payload=None):
        self._get_menu_payload = get_menu_payload
        base = os.path.dirname(os.path.abspath(__file__))
        assets = os.path.abspath(assets_path or os.path.join(base, "..", "assets"))
        tmp = tempfile.gettempdir()
        uid = os.getuid()
        socket_path = os.path.join(tmp, f"gha-notifier-{uid}.sock")
        self._menu_file = os.path.join(tmp, f"gha-notifier-{uid}-menu.txt")
        env = {**os.environ, SOCKET_ENV: socket_path, MENU_FILE_ENV: self._menu_file, ASSETS_ENV: assets}

        t = threading.Thread(target=_server_loop, args=(socket_path, on_command), daemon=True)
        t.start()
        time.sleep(0.15)

        script = os.path.abspath(__file__)
        try:
            self._process = subprocess.Popen(
                [sys.executable, script, "--indicator"],
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            self._process = None
        if self._process and self._get_menu_payload:
            try:
                open(self._menu_file, "w", encoding="utf-8").write(self._get_menu_payload())
            except Exception:
                pass

    def shutdown(self):
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=2)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None
        try:
            if self._menu_file and os.path.isfile(self._menu_file):
                os.unlink(self._menu_file)
        except Exception:
            pass

    def rebuild_menu(self):
        if not self._get_menu_payload or not self._menu_file:
            return
        try:
            open(self._menu_file, "w", encoding="utf-8").write(self._get_menu_payload())
        except Exception:
            pass


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--indicator":
        run_indicator()
    else:
        sys.exit("Run with --indicator from the main app.")
