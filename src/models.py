"""GObject models for list/table views (ColumnView, etc.) and config data models."""

from gi.repository import GObject

from formatters import conclusion_color


class RepoConfig:
    """Model for a repository entry in config['repos']. Shape used by pollers, manage_branches, and repo_dialog."""

    __slots__ = ("owner", "repo", "branches", "auto_add_pr_branches")

    def __init__(
        self,
        owner="",
        repo="",
        branches=None,
        auto_add_pr_branches=False,
    ):
        self.owner = (owner or "").strip()
        self.repo = (repo or "").strip()
        self.branches = list(branches or [])
        self.auto_add_pr_branches = bool(auto_add_pr_branches)

    @property
    def repo_key(self):
        """Return 'owner/repo' identifier."""
        if self.owner and self.repo:
            return f"{self.owner}/{self.repo}"
        return ""

    @classmethod
    def from_dict(cls, d):
        """Build RepoConfig from a config dict (owner, repo, branches, autoAddPRBranches)."""
        if d is None:
            return cls()
        return cls(
            owner=d.get("owner", ""),
            repo=d.get("repo", ""),
            branches=d.get("branches") or [],
            auto_add_pr_branches=bool(d.get("autoAddPRBranches")),
        )

    def to_dict(self):
        """Serialize to config dict for JSON."""
        return {
            "owner": self.owner,
            "repo": self.repo,
            "branches": self.branches,
            "autoAddPRBranches": self.auto_add_pr_branches,
        }


class WatchRow(GObject.Object):
    """Single row for the Watches tab (GListModel item)."""

    __gtype_name__ = "WatchRow"
    repo_key = GObject.Property(type=str, default="")  # full "owner/repo" for API
    repo = GObject.Property(type=str, default="")
    branch = GObject.Property(type=str, default="")
    workflow_name = GObject.Property(type=str, default="")
    status = GObject.Property(type=str, default="")
    duration = GObject.Property(type=str, default="")
    commit_msg = GObject.Property(type=str, default="")
    author = GObject.Property(type=str, default="")
    triggered = GObject.Property(type=str, default="")
    url = GObject.Property(type=str, default="")
    run_id = GObject.Property(type=str, default="0")  # the run we're watching (primary key)

    def __init__(
        self,
        repo_key,
        repo,
        branch,
        workflow_name,
        status,
        duration,
        commit_msg,
        author,
        triggered,
        url,
        run_id=0,
    ):
        super().__init__()
        self.repo_key = repo_key or ""
        self.repo = repo or ""
        self.branch = branch or ""
        self.workflow_name = workflow_name or "Workflow"
        self.status = status or "—"
        self.duration = duration or "—"
        self.commit_msg = commit_msg or "—"
        self.author = author or "—"
        self.triggered = triggered or "—"
        self.url = url or ""
        self.run_id = str(int(run_id or 0))


class WorkflowRunRow(GObject.Object):
    """Single row for the workflow runs ColumnView (GListModel item)."""

    __gtype_name__ = "WorkflowRunRow"
    name = GObject.Property(type=str, default="")
    status = GObject.Property(type=str, default="")
    conclusion = GObject.Property(type=str, default="")
    conclusion_markup = GObject.Property(type=str, default="")
    duration = GObject.Property(type=str, default="")
    commit_msg = GObject.Property(type=str, default="")
    author = GObject.Property(type=str, default="")
    triggered = GObject.Property(type=str, default="")
    watch = GObject.Property(type=bool, default=False)
    url = GObject.Property(type=str, default="")
    workflow_id = GObject.Property(type=str, default="0")  # string to hold large GitHub IDs
    run_id = GObject.Property(type=str, default="0")  # string to hold large GitHub IDs

    def __init__(
        self,
        name,
        status,
        conclusion,
        duration,
        commit_msg,
        author,
        triggered,
        watch,
        url,
        workflow_id,
        run_id=0,
    ):
        super().__init__()
        self.name = name
        self.status = status
        self.conclusion = conclusion or ""
        self.conclusion_markup = (
            f'<span foreground="{conclusion_color(conclusion)}">{conclusion or "—"}</span>'
            if conclusion
            else "—"
        )
        self.duration = duration
        self.commit_msg = commit_msg
        self.author = author
        self.triggered = triggered
        self.watch = watch
        self.url = url or ""
        self.workflow_id = str(int(workflow_id or 0))
        self.run_id = str(int(run_id or 0))
