"""Repository add/edit dialog."""

from gi.repository import Gtk

from models import RepoConfig
from ui_helpers import dialog_action_area_padding, dialog_content_padding


class RepoDialog(Gtk.Dialog):
    def __init__(self, parent, repo=None):
        super().__init__()
        self.set_title("Repository")
        self.set_transient_for(parent)
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("Save", Gtk.ResponseType.OK)
        self.set_modal(True)
        self.owner_entry = Gtk.Entry()
        self.repo_entry = Gtk.Entry()
        self.branches_entry = Gtk.Entry()
        grid = Gtk.Grid()
        grid.set_column_spacing(12)
        grid.set_row_spacing(8)
        grid.attach(Gtk.Label(label="Owner"), 0, 0, 1, 1)
        grid.attach(self.owner_entry, 1, 0, 1, 1)
        grid.attach(Gtk.Label(label="Repo"), 0, 1, 1, 1)
        grid.attach(self.repo_entry, 1, 1, 1, 1)
        grid.attach(
            Gtk.Label(label="Branches (comma-separated)"), 0, 2, 1, 1
        )
        grid.attach(self.branches_entry, 1, 2, 1, 1)
        if repo is not None:
            r = RepoConfig.from_dict(repo) if isinstance(repo, dict) else repo
            self.owner_entry.set_text(r.owner)
            self.repo_entry.set_text(r.repo)
            self.branches_entry.set_text(", ".join(r.branches))
        content = self.get_content_area()
        content.set_spacing(12)
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        dialog_content_padding(inner)
        inner.append(grid)
        content.append(inner)
        dialog_action_area_padding(self)

    def get_repo(self):
        """Return the entered repository as a RepoConfig."""
        return RepoConfig(
            owner=self.owner_entry.get_text().strip(),
            repo=self.repo_entry.get_text().strip(),
            branches=[
                b.strip()
                for b in self.branches_entry.get_text().split(",")
                if b.strip()
            ],
        )
