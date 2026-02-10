"""Modal dialogs."""

from .manage_branches import BRANCHES_PER_PAGE, ManageBranchesDialog
from .repo_dialog import RepoDialog
from .settings import SettingsDialog
from .token_login import TokenLoginDialog
from .workflow_branch_settings import WorkflowBranchSettingsDialog

__all__ = [
    "BRANCHES_PER_PAGE",
    "ManageBranchesDialog",
    "RepoDialog",
    "SettingsDialog",
    "TokenLoginDialog",
    "WorkflowBranchSettingsDialog",
]
