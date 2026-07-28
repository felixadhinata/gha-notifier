"""App-wide GTK4 CSS: a warm-neutral palette with a single accent, applied once at startup."""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gtk

CSS = """
@define-color gha_bg #f5f3f0;
@define-color gha_surface #ffffff;
@define-color gha_surface_sunken #edeae4;
@define-color gha_border #ddd8d0;
@define-color gha_border_strong #c7c0b4;
@define-color gha_text #221f1a;
@define-color gha_text_muted #756f63;
@define-color gha_accent #2f5f8a;
@define-color gha_accent_soft #e3edf4;
@define-color gha_success #2f8f4e;
@define-color gha_fail #c0392b;
@define-color gha_running #b9770e;

.gha-window {
  background-color: @gha_bg;
  color: @gha_text;
}

.gha-headerbar {
  background-color: @gha_surface;
}

.gha-avatar {
  background-color: @gha_accent_soft;
  color: @gha_accent;
  font-weight: 700;
  font-size: 12px;
  border-radius: 999px;
  min-width: 26px;
  min-height: 26px;
}

.gha-hint {
  color: @gha_text_muted;
}

button.gha-primary {
  background-image: none;
  background-color: @gha_accent;
  color: #ffffff;
  border: none;
  border-radius: 7px;
}
button.gha-primary:hover {
  background-image: none;
  background-color: shade(@gha_accent, 1.1);
}

button.gha-add-repo {
  background-image: none;
  background-color: @gha_surface;
  border: 1px solid @gha_border_strong;
  border-radius: 7px;
  color: @gha_text;
}
button.gha-add-repo:hover {
  background-image: none;
  background-color: @gha_surface_sunken;
}

.gha-sidebar {
  background-color: @gha_surface_sunken;
  border-radius: 10px;
}

.gha-section-label {
  color: @gha_text_muted;
  font-weight: 700;
  font-size: 11px;
}

frame.gha-card {
  background-color: @gha_surface;
  border: 1px solid @gha_border;
  border-radius: 10px;
}
frame.gha-card > border {
  border: none;
}

list.gha-repo-list {
  background: transparent;
}
list.gha-repo-list row {
  border-radius: 7px;
  margin: 2px 6px;
  padding: 2px;
}
list.gha-repo-list row:hover {
  background-color: alpha(@gha_border_strong, 0.35);
}
list.gha-repo-list row:selected {
  background-color: @gha_accent;
  color: #ffffff;
}
list.gha-repo-list row:selected button.flat {
  color: #ffffff;
}

.status-dot {
  min-width: 9px;
  min-height: 9px;
  border-radius: 999px;
  margin-top: 1px;
}
.status-dot.yellow { background-color: @gha_running; }
.status-dot.green { background-color: @gha_success; }
.status-dot.red { background-color: @gha_fail; }
.status-dot.gray { background-color: alpha(@gha_text_muted, 0.45); }

.gha-empty-state {
  color: @gha_text_muted;
}
.gha-empty-icon {
  opacity: 0.4;
}
"""


def load_css():
    """Install the app CSS on the default display. Call once at startup."""
    provider = Gtk.CssProvider()
    provider.load_from_string(CSS)
    display = Gdk.Display.get_default()
    if display is not None:
        Gtk.StyleContext.add_provider_for_display(
            display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
