"""Add-repository dialog: search your GitHub repos or type owner/repo directly."""

import threading

from gi.repository import GLib, Gtk

from config import get_repos
import store
from ui_helpers import clear_box, dialog_action_area_padding, dialog_content_padding


class AddRepoDialog(Gtk.Dialog):
    def __init__(self, parent):
        super().__init__()
        self.set_title("Add repository")
        self.set_transient_for(parent)
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.add_btn = self.add_button("Add", Gtk.ResponseType.OK)
        self.add_btn.set_sensitive(False)
        self.set_default_size(420, 480)
        self.set_modal(True)

        content = self.get_content_area()
        content.set_spacing(12)
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        dialog_content_padding(inner)

        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text("owner/repo, or search your repositories…")
        self.search_entry.connect("search-changed", lambda e: self._on_search_changed())
        self.search_entry.connect("activate", lambda e: self._try_submit())
        inner.append(self.search_entry)

        self.list_box = Gtk.ListBox()
        self.list_box.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.list_box.connect("row-activated", self._on_row_activated)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.set_child(self.list_box)
        scroll.set_vexpand(True)
        frame = Gtk.Frame()
        frame.set_child(scroll)
        frame.set_vexpand(True)
        inner.append(frame)

        self.hint_label = Gtk.Label(label="Loading your repositories…")
        self.hint_label.set_xalign(0)
        self.hint_label.set_wrap(True)
        inner.append(self.hint_label)

        content.append(inner)
        dialog_action_area_padding(self)

        self._all_repos = []
        self._already_added = set(get_repos(store.config))
        self._activated_repo = None
        threading.Thread(target=self._load_repos, daemon=True).start()

    def get_selected_repo(self):
        """Return the chosen 'owner/repo', from an activated row or typed text. None if invalid."""
        if self._activated_repo:
            return self._activated_repo
        text = (self.search_entry.get_text() or "").strip()
        owner, _, repo = text.partition("/")
        if owner.strip() and repo.strip():
            return text
        return None

    def _load_repos(self):
        try:
            repos = store.client.get_user_repos()
            names = sorted({r.get("full_name") for r in repos if r.get("full_name")})
        except Exception:
            names = []
        GLib.idle_add(self._on_repos_loaded, names)

    def _on_repos_loaded(self, names):
        self._all_repos = names
        self.hint_label.set_text('Select a repository, or type "owner/repo" above and press Enter.')
        self._refill_list()

    def _on_search_changed(self):
        self._activated_repo = None
        self._refill_list()

    def _refill_list(self):
        query = (self.search_entry.get_text() or "").strip().lower()
        clear_box(self.list_box)
        for name in self._all_repos:
            if name in self._already_added:
                continue
            if query and query not in name.lower():
                continue
            row = Gtk.ListBoxRow()
            row.repo_key = name
            lbl = Gtk.Label(label=name)
            lbl.set_xalign(0)
            lbl.set_margin_start(8)
            lbl.set_margin_end(8)
            lbl.set_margin_top(6)
            lbl.set_margin_bottom(6)
            row.set_child(lbl)
            self.list_box.append(row)
        self.add_btn.set_sensitive(bool(self.get_selected_repo()))

    def _on_row_activated(self, listbox, row):
        repo_key = getattr(row, "repo_key", None)
        if not repo_key:
            return
        self._activated_repo = repo_key
        self.add_btn.set_sensitive(True)
        self.response(Gtk.ResponseType.OK)

    def _try_submit(self):
        if self.get_selected_repo():
            self.response(Gtk.ResponseType.OK)
