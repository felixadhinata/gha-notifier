"""Workflow auto-watch settings dialog for a branch."""

from gi.repository import Gtk

from config import save_config
import store
from ui_helpers import dialog_action_area_padding, dialog_content_padding


class WorkflowBranchSettingsDialog(Gtk.Dialog):
    """Dialog to configure auto-watch workflows for the current branch."""

    def __init__(self, parent, repo_key, branch_name):
        super().__init__()
        self.set_title("Workflow settings for this branch")
        self.set_transient_for(parent)
        self.repo_key = repo_key
        self.branch_name = branch_name
        self.branch_key = f"{repo_key}:{branch_name}"
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("Apply", Gtk.ResponseType.OK)
        self.set_default_size(420, 180)
        self.set_modal(True)
        content = self.get_content_area()
        content.set_spacing(12)
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        dialog_content_padding(inner)
        settings = store.config.get("branchAutoWatch", {}).get(
            self.branch_key, {}
        )
        self.auto_watch_check = Gtk.CheckButton(
            label="Automatically watch workflows for this branch"
        )
        self.auto_watch_check.set_active(bool(settings.get("enabled")))
        self.auto_watch_check.connect(
            "toggled", lambda btn: self.patterns_row.set_visible(btn.get_active())
        )
        inner.append(self.auto_watch_check)
        patterns_row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        patterns_label = Gtk.Label(
            label="Workflow name contains (comma-separated):"
        )
        patterns_label.set_xalign(0)
        patterns_label.set_wrap(True)
        self.patterns_entry = Gtk.Entry()
        self.patterns_entry.set_placeholder_text("e.g. CI, build, test")
        self.patterns_entry.set_text(settings.get("patterns") or "")
        patterns_row.append(patterns_label)
        patterns_row.append(self.patterns_entry)
        inner.append(patterns_row)
        self.patterns_row = patterns_row
        self.patterns_row.set_visible(self.auto_watch_check.get_active())
        content.append(inner)
        dialog_action_area_padding(self)

    def apply(self):
        enabled = self.auto_watch_check.get_active()
        patterns = (self.patterns_entry.get_text() or "").strip()
        branch_auto = store.config.get("branchAutoWatch", {})
        if not isinstance(branch_auto, dict):
            branch_auto = {}
        branch_auto[self.branch_key] = {"enabled": enabled, "patterns": patterns}
        store.config["branchAutoWatch"] = branch_auto
        save_config(store.config)
