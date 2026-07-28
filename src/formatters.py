"""Formatting and status helpers for workflow runs and display."""

import time
from datetime import datetime, timezone


# Colored status display (● + label) shared by Watches tab and Workflow table
STATUS_COLORS = {"red": "#ef4444", "green": "#22c55e", "yellow": "#eab308", "gray": "#9ca3af", "orange": "#f97316"}
STATUS_LABELS = {"red": "failed", "green": "success", "yellow": "in progress", "gray": "—", "orange": "—"}


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------

def conclusion_color(conclusion):
    """Return a color name for conclusion text (success=green, failure=red, etc.)."""
    c = (conclusion or "").lower()
    if c == "success":
        return "green"
    if c in ("failure", "timed_out"):
        return "red"
    if c in ("cancelled", "skipped"):
        return "gray"
    return "orange"


def _parse_iso_to_epoch(iso_str):
    """Parse API ISO timestamp (UTC) to seconds since epoch. Returns None on failure."""
    if not iso_str:
        return None
    try:
        s = (iso_str.split(".")[0] or "").strip()
        if not s or "T" not in s:
            return None
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError):
        return None


def format_duration(started_at, updated_at):
    """Duration from started_at to updated_at. If updated_at is None (e.g. in-progress run), use current time (now - started_at)."""
    start_epoch = _parse_iso_to_epoch(started_at) if started_at else None
    if start_epoch is None:
        return "n/a"
    try:
        if updated_at:
            end_epoch = _parse_iso_to_epoch(updated_at)
            if end_epoch is None:
                return "n/a"
        else:
            end_epoch = time.time()
        seconds = int(end_epoch - start_epoch)
    except (ValueError, TypeError):
        return "n/a"
    minutes, secs = divmod(max(seconds, 0), 60)
    return f"{secs}s" if minutes == 0 else f"{minutes}m {secs}s"


def format_run_started_at(run_started_at):
    """Format workflow run start time for display in local time (e.g. 2024-01-15 14:32). API times are UTC."""
    if not run_started_at:
        return "—"
    try:
        s = (run_started_at.split(".")[0] or "").strip()
        if not s or "T" not in s:
            return "—"
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        local = dt.astimezone()
        return local.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "—"


def get_status_markup(status_color_name):
    """Return Pango markup for status: colored dot + label (e.g. ● success). status_color_name: green/red/yellow/gray/orange."""
    color = (status_color_name or "").strip().lower()
    hex_color = STATUS_COLORS.get(color, STATUS_COLORS["gray"])
    label = STATUS_LABELS.get(color, "—")
    return f"<span foreground='{hex_color}'>●</span> {label}"


def resolve_status(run):
    status = run.get("status")
    if status in ("in_progress", "queued"):
        return "yellow"
    if status == "completed":
        return "green" if run.get("conclusion") == "success" else "red"
    return "gray"


def status_color_from_run(status, conclusion):
    """Return status color name (green/red/yellow/gray) from run status and conclusion. For use with get_status_markup."""
    return resolve_status({"status": status, "conclusion": conclusion or ""})
