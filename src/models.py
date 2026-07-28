"""GObject models for list/table views (ColumnView, etc.)."""

from gi.repository import GObject


class RunRow(GObject.Object):
    """Single row for the workflow runs table shown when a repo is selected."""

    __gtype_name__ = "RunRow"
    name = GObject.Property(type=str, default="")
    branch = GObject.Property(type=str, default="")
    status = GObject.Property(type=str, default="")
    conclusion = GObject.Property(type=str, default="")
    duration = GObject.Property(type=str, default="")
    commit_msg = GObject.Property(type=str, default="")
    author = GObject.Property(type=str, default="")
    triggered = GObject.Property(type=str, default="")
    url = GObject.Property(type=str, default="")
    run_id = GObject.Property(type=str, default="0")  # string to hold large GitHub IDs

    def __init__(
        self,
        name,
        branch,
        status,
        conclusion,
        duration,
        commit_msg,
        author,
        triggered,
        url,
        run_id=0,
    ):
        super().__init__()
        self.name = name or "Workflow"
        self.branch = branch or "—"
        self.status = status or ""
        self.conclusion = conclusion or ""
        self.duration = duration or "—"
        self.commit_msg = commit_msg or "—"
        self.author = author or "—"
        self.triggered = triggered or "—"
        self.url = url or ""
        self.run_id = str(int(run_id or 0))
