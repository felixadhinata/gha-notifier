"""Icon and fatal error UI."""

import os

from gi.repository import Gtk


def icon_path(color):
    """Return path to SVG icon for status color (e.g. green, red, yellow, gray)."""
    base = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "assets")
    )
    return os.path.join(base, f"icon-{color}.svg")


def show_fatal_error(message):
    """Show error dialog when no app/window exists (e.g. before activate or in excepthook)."""
    app = Gtk.Application(application_id="org.gha-notifier.fatal")

    def on_activate(application):
        win = Gtk.ApplicationWindow(application=application)
        win.set_decorated(False)
        win.set_opacity(0)
        win.set_default_size(1, 1)
        dialog = Gtk.Dialog(
            transient_for=win, modal=True, title="GHA Notifier – Error"
        )
        dialog.add_button("Close", Gtk.ResponseType.CLOSE)
        area = dialog.get_content_area()
        area.set_margin_start(18)
        area.set_margin_end(18)
        area.set_margin_top(18)
        area.set_margin_bottom(18)
        lbl = Gtk.Label(label=message)
        lbl.set_wrap(True)
        lbl.set_selectable(True)
        area.append(lbl)
        dialog.connect("response", lambda d, r: application.quit())
        dialog.present()

    app.connect("activate", on_activate)
    app.run(None)
