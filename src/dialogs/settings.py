"""App settings dialog."""

from gi.repository import Gtk

from config import save_config, set_open_on_startup
import store
from ui_helpers import dialog_action_area_padding, dialog_content_padding


class SettingsDialog(Gtk.Dialog):
    def __init__(self, parent, app=None):
        super().__init__()
        self.app = app
        self.set_title("Settings")
        self.set_transient_for(parent)
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("Apply", Gtk.ResponseType.OK)
        self.set_default_size(320, 220)
        self.set_modal(True)
        content = self.get_content_area()
        content.set_spacing(12)
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        dialog_content_padding(inner)

        grid = Gtk.Grid()
        grid.set_column_spacing(12)
        grid.set_row_spacing(8)
        interval_label = Gtk.Label(label="Poll interval (seconds)")
        interval_label.set_xalign(0)
        self.interval_spin = Gtk.SpinButton()
        self.interval_spin.set_adjustment(Gtk.Adjustment.new(20, 10, 300, 1, 5, 0))
        self.interval_spin.set_value(float(store.config.get("pollIntervalSec", 20)))
        grid.attach(interval_label, 0, 0, 1, 1)
        grid.attach(self.interval_spin, 1, 0, 1, 1)
        inner.append(grid)

        self.notify_check = Gtk.CheckButton(label="Enable desktop notifications")
        self.notify_check.set_active(store.config.get("notifyEnabled", True))
        inner.append(self.notify_check)

        self.open_on_startup_check = Gtk.CheckButton(label="Open on program startup")
        self.open_on_startup_check.set_tooltip_text("Start GHA Notifier when you log in")
        self.open_on_startup_check.set_active(store.config.get("openOnStartup", False))
        inner.append(self.open_on_startup_check)

        content.append(inner)
        dialog_action_area_padding(self)

    def apply(self):
        store.config["pollIntervalSec"] = int(self.interval_spin.get_value())
        store.config["notifyEnabled"] = self.notify_check.get_active()
        store.config["openOnStartup"] = self.open_on_startup_check.get_active()
        save_config(store.config)
        store.start_polling()
        exec_cmd = self.app.get_autostart_exec_command() if self.app else None
        set_open_on_startup(store.config["openOnStartup"], exec_cmd or "")
