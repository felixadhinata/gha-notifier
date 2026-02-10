"""Shared UI helpers for GTK 4 dialogs and containers."""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("GLib", "2.0")
from gi.repository import GLib, Gtk


def dialog_content_padding(widget, margin=18):
    """Apply uniform margin to a widget (e.g. dialog content box)."""
    widget.set_margin_start(margin)
    widget.set_margin_end(margin)
    widget.set_margin_top(margin)
    widget.set_margin_bottom(margin)


def dialog_action_area_padding(
    dialog, margin=18, top=12, button_spacing=16, button_margin=8
):
    """Add padding around the dialog's Cancel/Apply (or other) button area in GTK 4."""
    main = dialog.get_child()
    if main is None:
        return
    last = main.get_last_child()
    if last is not None:
        last.set_margin_start(margin)
        last.set_margin_end(margin)
        last.set_margin_bottom(margin)
        last.set_margin_top(top)
        last.set_spacing(button_spacing)
        child = last.get_first_child()
        while child:
            child.set_margin_start(button_margin)
            child.set_margin_end(button_margin)
            child = child.get_next_sibling()


def run_dialog_modal(dialog):
    """Run a dialog modally (GTK 4 has no dialog.run()). Returns response id."""
    result = [None]

    def on_response(_d, response_id):
        result[0] = response_id
        loop.quit()

    dialog.connect("response", on_response)
    dialog.present()
    loop = GLib.MainLoop()
    loop.run()
    return result[0]


def clear_box(widget):
    """Remove all children from a GTK 4 container (Box, ListBox, etc.). Uses remove_all() for ListBox to avoid stale refs; otherwise removes first child repeatedly."""
    if isinstance(widget, Gtk.ListBox):
        widget.remove_all()
        return
    while True:
        child = widget.get_first_child()
        if child is None:
            break
        child.unparent()
