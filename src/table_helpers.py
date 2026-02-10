"""Shared column view factories and helpers for GTK 4 ColumnView tables."""

import webbrowser

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gtk, Pango

from formatters import get_status_markup


def _disconnect_notify(item, attr):
    """If item has attr (obj, hid), disconnect and remove. Safe if already disconnected."""
    if not hasattr(item, attr):
        return
    obj, hid = getattr(item, attr)
    try:
        obj.disconnect(hid)
    except Exception:
        pass
    delattr(item, attr)


def text_factory(prop, ellipsize=True):
    """SignalListItemFactory for a text column bound to `prop`. Listens for property changes so labels stay in sync."""
    factory = Gtk.SignalListItemFactory()
    attr = "_tf_notify_" + prop
    notify_signal = "notify::" + prop.replace("_", "-")

    def setup(_fac, item):
        lbl = Gtk.Label()
        if ellipsize:
            lbl.set_ellipsize(Pango.EllipsizeMode.END)
        lbl.set_xalign(0)
        item.set_child(lbl)

    def bind(_fac, item):
        obj = item.get_item()
        lbl = item.get_child() if item else None
        if not obj or not lbl:
            return
        lbl.set_label(str(getattr(obj, prop, "") or "—"))
        _disconnect_notify(item, attr)
        def on_notify(_o, _pspec, l=lbl, p=prop):
            l.set_label(str(getattr(_o, p, "") or "—"))
        setattr(item, attr, (obj, obj.connect(notify_signal, on_notify)))

    def unbind(_fac, item):
        _disconnect_notify(item, attr)

    factory.connect("setup", setup)
    factory.connect("bind", bind)
    factory.connect("unbind", unbind)
    return factory


def make_status_factory(get_color_from_row, notify_prop="status"):
    """Return a SignalListItemFactory for a status column (colored dot + label).
    get_color_from_row(row_obj) must return status color name (green/red/yellow/gray).
    Listens for notify::notify_prop so the column updates when the row changes."""
    factory = Gtk.SignalListItemFactory()
    attr = "_status_factory_notify"
    notify_signal = "notify::" + notify_prop.replace("_", "-")

    def setup(_fac, item):
        lbl = Gtk.Label()
        lbl.set_ellipsize(Pango.EllipsizeMode.END)
        lbl.set_xalign(0)
        item.set_child(lbl)

    def bind(_fac, item):
        obj = item.get_item()
        lbl = item.get_child() if item else None
        if not obj or not lbl:
            return
        color = get_color_from_row(obj)
        lbl.set_markup(get_status_markup(color or ""))
        _disconnect_notify(item, attr)
        def on_notify(_o, _pspec, get_color=get_color_from_row, label=lbl):
            c = get_color(_o)
            label.set_markup(get_status_markup(c or ""))
        setattr(item, attr, (obj, obj.connect(notify_signal, on_notify)))

    def unbind(_fac, item):
        _disconnect_notify(item, attr)

    factory.connect("setup", setup)
    factory.connect("bind", bind)
    factory.connect("unbind", unbind)
    return factory


def add_column(column_view, title, factory, *, expand=False, min_width=100):
    """Append a column to column_view with the given title and factory."""
    col = Gtk.ColumnViewColumn(title=title, factory=factory)
    col.set_resizable(True)
    col.set_expand(expand)
    if min_width > 0:
        col.set_fixed_width(min_width)
    column_view.append_column(col)


def make_open_url_factory(url_prop="url"):
    """Return a SignalListItemFactory for an 'Open' button that opens the row's URL."""
    _hids = {}
    factory = Gtk.SignalListItemFactory()
    def setup(_f, item):
        item.set_child(Gtk.Button(label="Open"))
    def bind(_f, item):
        obj = item.get_item()
        btn = item.get_child()
        if obj and btn:
            hid = _hids.pop(id(btn), None)
            if hid is not None:
                btn.disconnect(hid)
            url = (getattr(obj, url_prop, None) or "").strip()
            btn.set_sensitive(bool(url))
            if url:
                hid = btn.connect("clicked", lambda *_, u=url: webbrowser.open(u))
                _hids[id(btn)] = hid
    def unbind(_f, item):
        btn = item.get_child()
        _hids.pop(id(btn), None)
    factory.connect("setup", setup)
    factory.connect("bind", bind)
    factory.connect("unbind", unbind)
    return factory
