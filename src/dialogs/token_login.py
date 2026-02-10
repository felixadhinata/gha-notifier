"""Token-based login dialog."""

from gi.repository import Gtk

from ui_helpers import dialog_action_area_padding, dialog_content_padding


class TokenLoginDialog(Gtk.Dialog):
    GITHUB_TOKENS_URL = "https://github.com/settings/tokens/new?scopes=repo,workflow,read:user&description=GHA+Notifier"

    def __init__(self, parent):
        super().__init__(title="Sign in with token", transient_for=parent)
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("Sign in", Gtk.ResponseType.OK)
        self.set_default_size(420, 180)
        self.set_modal(True)
        content = self.get_content_area()
        content.set_spacing(12)
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        dialog_content_padding(inner, margin=18)
        hint = Gtk.Label(
            label="Required access: repo, workflow, read:user (repos, Actions, profile)."
        )
        hint.set_xalign(0)
        hint.set_wrap(True)
        link_btn = Gtk.LinkButton(
            uri=self.GITHUB_TOKENS_URL,
            label="Open GitHub: New Personal Access Token",
        )
        link_btn.set_halign(Gtk.Align.START)
        self.token_entry = Gtk.Entry()
        self.token_entry.set_placeholder_text("Paste your token here")
        self.token_entry.set_visibility(False)
        self.token_entry.set_invisible_char("*")
        inner.append(hint)
        inner.append(link_btn)
        inner.append(self.token_entry)
        content.append(inner)
        dialog_action_area_padding(self)

    def get_token(self):
        return self.token_entry.get_text().strip()
