"""
Desktop notifications: prefer libnotify (reliable on Linux), fallback to Gio.Notification, then notify-send.
Plays a notification sound when supported (canberra-gtk-play or paplay).
"""
import subprocess
import webbrowser

# Keep ref so libnotify action callback is not garbage-collected
_notify_refs = []

# Default for the "enable notifications" setting (used when config is not yet loaded)
DEFAULT_NOTIFY_ENABLED = True

def _play_notification_sound():
    """Play a short notification sound. Non-blocking; tries canberra-gtk-play then paplay with system sound."""
    def run():
        try:
            subprocess.run(
                ["canberra-gtk-play", "-i", "message-new-instant"],
                timeout=2,
                capture_output=True,
                stdin=subprocess.DEVNULL,
            )
        except (subprocess.TimeoutExpired, OSError):
            try:
                subprocess.run(
                    ["paplay", "/usr/share/sounds/freedesktop/stereo/message-new-instant.oga"],
                    timeout=2,
                    capture_output=True,
                    stdin=subprocess.DEVNULL,
                )
            except (subprocess.TimeoutExpired, OSError):
                pass

    try:
        import threading
        threading.Thread(target=run, daemon=True).start()
    except Exception:
        pass


def is_enabled():
    """Return True if notifications are enabled (read from config). Default True."""
    try:
        import store
        cfg = getattr(store, "config", None)
        if cfg is None:
            return DEFAULT_NOTIFY_ENABLED
        return bool(cfg.get("notifyEnabled", DEFAULT_NOTIFY_ENABLED))
    except Exception:
        return DEFAULT_NOTIFY_ENABLED


def notify(
    title: str = "Notification",
    body: str = "",
    url: str | None = None,
):
    """
    Show a desktop notification. If url is set, clicking can open it.
    Tries libnotify first (reliable on Linux), then Gio.Notification, then notify-send.
    Does nothing if notifications are disabled in settings.
    """
    if not is_enabled():
        return
    _play_notification_sound()
    url = (url or "").strip()

    try:
        import gi
        gi.require_version("Notify", "0.7")
        from gi.repository import Notify
        Notify.init("GHA Notifier")
        n = Notify.Notification.new(title, body)
        if url:
            def _on_action(_n, _key, data):
                if data:
                    webbrowser.open(data)
            n.add_action("default", "Open", _on_action, url)
            _notify_refs.append(n)
            def _on_closed(notif, *_):
                try:
                    _notify_refs.remove(notif)
                except ValueError:
                    pass
            n.connect("closed", _on_closed)
        n.show()
        return
    except (ValueError, ImportError):
        pass
