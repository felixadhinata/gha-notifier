"""Tab UI builders for Branches & Workflows and Watches."""

from .branches_workflows import (
    build_branches_workflows_tab,
    build_workflows_table,
    refill_branch_list,
    refresh_workflows_for_selection,
    render_branches_list,
    toggle_watch,
)
from .watches import build_watches_tab, clear_completed_watches, fill_watches_store, refresh_watches_tab

__all__ = [
    "build_branches_workflows_tab",
    "build_watches_tab",
    "clear_completed_watches",
    "fill_watches_store",
    "build_workflows_table",
    "refill_branch_list",
    "refresh_watches_tab",
    "refresh_workflows_for_selection",
    "render_branches_list",
    "toggle_watch",
]
