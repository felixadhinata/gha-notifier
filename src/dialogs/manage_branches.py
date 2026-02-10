"""Add / Delete branch dialog (repository and branch selection)."""

import threading

from gi.repository import GLib, Gtk

from config import get_repos, save_config, set_repos
from models import RepoConfig
import store
from ui_helpers import clear_box, dialog_action_area_padding, dialog_content_padding

BRANCHES_PER_PAGE = 30


class ManageBranchesDialog(Gtk.Dialog):
    def __init__(self, parent):
        super().__init__()
        self.set_title("Add / Delete branch")
        self.set_transient_for(parent)
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("Apply", Gtk.ResponseType.OK)
        self.set_default_size(720, 800)
        self.set_modal(True)
        content = self.get_content_area()
        content.set_spacing(12)
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        dialog_content_padding(inner)
        repo_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        repo_label = Gtk.Label()
        repo_label.set_markup("<b>Repository</b>")
        repo_label.set_xalign(0)
        self.repo_spinner = Gtk.Spinner()
        repo_spacer = Gtk.Box()
        repo_spacer.set_hexpand(True)
        repo_header.append(repo_label)
        repo_header.append(self.repo_spinner)
        repo_header.append(repo_spacer)
        inner.append(repo_header)
        self.repo_search = Gtk.SearchEntry()
        self.repo_search.set_placeholder_text("Search repository…")
        self.repo_search.connect("search-changed", lambda e: self._refill_repo_list())
        inner.append(self.repo_search)
        self.repo_list = Gtk.ListBox()
        self.repo_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.repo_list.set_size_request(-1, 260)
        self.repo_list.connect("row-activated", self._on_repo_selected)
        scroll_repos = Gtk.ScrolledWindow()
        scroll_repos.set_policy(
            Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC
        )
        scroll_repos.set_child(self.repo_list)
        scroll_repos.set_vexpand(True)
        repo_list_frame = Gtk.Frame()
        repo_list_frame.set_child(scroll_repos)
        repo_list_frame.set_vexpand(True)
        inner.append(repo_list_frame)
        branch_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        branch_label = Gtk.Label()
        branch_label.set_markup("<b>Branches</b>")
        branch_label.set_xalign(0)
        self.branch_spinner = Gtk.Spinner()
        branch_spacer = Gtk.Box()
        branch_spacer.set_hexpand(True)
        self.branch_clear_all_btn = Gtk.Button(label="Clear all")
        self.branch_clear_all_btn.set_tooltip_text(
            "Uncheck all branches for the selected repository"
        )
        self.branch_clear_all_btn.connect(
            "clicked", self._on_clear_all_branches
        )
        branch_header.append(branch_label)
        branch_header.append(self.branch_spinner)
        branch_header.append(branch_spacer)
        branch_header.append(self.branch_clear_all_btn)
        inner.append(branch_header)
        self.branch_search = Gtk.SearchEntry()
        self.branch_search.set_placeholder_text("Search branch…")
        self.branch_search.connect("search-changed", self._on_branch_search_changed)
        inner.append(self.branch_search)
        self.branch_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        scroll_branches = Gtk.ScrolledWindow()
        scroll_branches.set_policy(
            Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC
        )
        scroll_branches.set_size_request(-1, 220)
        scroll_branches.set_child(self.branch_box)
        scroll_branches.set_vexpand(True)
        branch_list_frame = Gtk.Frame()
        branch_list_frame.set_child(scroll_branches)
        branch_list_frame.set_vexpand(True)
        inner.append(branch_list_frame)
        branch_pagination_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=8
        )
        self.branch_prev_btn = Gtk.Button(label="Previous")
        self.branch_prev_btn.connect("clicked", self._on_branch_prev)
        self.branch_page_label = Gtk.Label(label="")
        self.branch_page_label.set_hexpand(True)
        self.branch_next_btn = Gtk.Button(label="Next")
        self.branch_next_btn.connect("clicked", self._on_branch_next)
        branch_pagination_box.append(self.branch_prev_btn)
        branch_pagination_box.append(self.branch_page_label)
        branch_pagination_box.append(self.branch_next_btn)
        inner.append(branch_pagination_box)
        self.auto_add_pr_branches_check = Gtk.CheckButton(
            label="Automatically add branches from your pull requests in (select a repository)"
        )
        self.auto_add_pr_branches_check.set_tooltip_text(
            "Append branches from your open PRs in the selected repository to the list (saved per repo in store.config)"
        )
        inner.append(self.auto_add_pr_branches_check)
        content.append(inner)
        inner.set_vexpand(True)
        self._repos_data = []
        self._selected_full_name = None
        self._branch_checks = []
        self._cached_branch_names = []
        self._branch_loading_all = False
        self._branch_page = 1
        self._selected_branch_names_for_repo = set()
        self.branch_clear_all_btn.set_sensitive(False)
        dialog_action_area_padding(self)
        self._set_repo_loading(True)
        self._hide_branch_loading()
        self._update_branch_pagination_visibility(False)
        threading.Thread(target=self._load_repos, daemon=True).start()

    def _set_repo_loading(self, loading):
        if loading:
            self.repo_spinner.start()
            self.repo_spinner.set_visible(True)
            self.repo_list.set_sensitive(False)
            self.repo_search.set_sensitive(False)
        else:
            self.repo_spinner.stop()
            self.repo_spinner.set_visible(False)
            self.repo_list.set_sensitive(True)
            self.repo_search.set_sensitive(True)

    def _show_branch_loading(self):
        self.branch_spinner.start()
        self.branch_spinner.set_visible(True)
        self.branch_box.set_sensitive(False)
        self.branch_search.set_sensitive(False)
        self.branch_prev_btn.set_sensitive(False)
        self.branch_next_btn.set_sensitive(False)

    def _hide_branch_loading(self):
        self.branch_spinner.stop()
        self.branch_spinner.set_visible(False)
        self.branch_box.set_sensitive(True)
        self.branch_search.set_sensitive(True)

    def _update_branch_pagination_visibility(self, visible):
        self.branch_prev_btn.set_visible(visible)
        self.branch_page_label.set_visible(visible)
        self.branch_next_btn.set_visible(visible)

    def _get_selected_branches_for_repo(self, owner, repo):
        for r in get_repos(store.config):
            if r.owner == owner and r.repo == repo:
                return list(r.branches)
        return []

    def _update_auto_add_pr_check_label(self):
        if self._selected_full_name:
            self.auto_add_pr_branches_check.set_label(
                f"Automatically add branches from your pull requests in {self._selected_full_name}"
            )
            self.auto_add_pr_branches_check.set_sensitive(True)
            for r in get_repos(store.config):
                if r.repo_key == self._selected_full_name:
                    self.auto_add_pr_branches_check.set_active(
                        r.auto_add_pr_branches
                    )
                    break
            else:
                self.auto_add_pr_branches_check.set_active(False)
        else:
            self.auto_add_pr_branches_check.set_label(
                "Automatically add branches from your pull requests in (select a repository)"
            )
            self.auto_add_pr_branches_check.set_sensitive(False)

    def _filtered_repos(self):
        q = (self.repo_search.get_text() or "").strip().lower()
        if not q:
            return self._repos_data
        return [n for n in self._repos_data if q in n.lower()]

    def _refill_repo_list(self):
        filtered = self._filtered_repos()
        clear_box(self.repo_list)
        for name in filtered:
            row = Gtk.ListBoxRow()
            lbl = Gtk.Label(label=name)
            lbl.set_xalign(0)
            lbl.set_margin_start(8)
            lbl.set_margin_end(8)
            lbl.set_margin_top(4)
            lbl.set_margin_bottom(4)
            row.set_child(lbl)
            self.repo_list.append(row)

    def _load_repos(self):
        try:
            repos = store.client.get_user_repos()
            api_names = [
                r.get("full_name")
                or f"{r.get('owner', {}).get('login')}/{r.get('name')}"
                for r in repos
            ]
            config_names = [r.repo_key for r in get_repos(store.config)]
            full_names = sorted(set(config_names) | set(api_names))
            GLib.idle_add(self._populate_repos, full_names)
        except Exception:
            GLib.idle_add(self._populate_repos, [])

    def _populate_repos(self, full_names):
        self._set_repo_loading(False)
        self._repos_data = full_names
        self._refill_repo_list()

    def _on_repo_selected(self, listbox, row):
        if not row:
            return
        filtered = self._filtered_repos()
        idx = row.get_index()
        if idx < 0 or idx >= len(filtered):
            return
        self._selected_full_name = filtered[idx]
        self._update_auto_add_pr_check_label()
        self._cached_branch_names = []
        self._branch_loading_all = True
        self._branch_page = 1
        self._show_branch_loading()
        clear_box(self.branch_box)
        self._branch_checks.clear()
        self._update_branch_pagination_visibility(False)
        threading.Thread(
            target=self._load_all_branches,
            args=(self._selected_full_name,),
            daemon=True,
        ).start()

    def _load_all_branches(self, full_name):
        try:
            owner, repo = full_name.split("/", 1)
            selected = self._get_selected_branches_for_repo(owner, repo)
            page = 1
            while True:
                branches = store.client.get_branches(
                    owner, repo, page=page, per_page=100
                )
                names = [b.get("name") for b in branches if b.get("name")]
                has_more = len(names) >= 100
                is_first = page == 1
                GLib.idle_add(
                    self._on_branches_chunk_loaded,
                    full_name,
                    names,
                    has_more,
                    is_first,
                    selected if is_first else None,
                )
                if not has_more:
                    break
                page += 1
        except Exception as e:
            GLib.idle_add(
                self._on_branches_chunk_loaded,
                full_name,
                [],
                False,
                True,
                None,
                str(e),
            )

    def _on_branches_chunk_loaded(
        self, full_name, names, has_more, is_first, selected_names, error_msg=None
    ):
        if is_first:
            if error_msg:
                self._hide_branch_loading()
                self._branch_loading_all = False
                clear_box(self.branch_box)
                lbl = Gtk.Label(label=f"Failed to load branches: {error_msg}")
                lbl.set_wrap(True)
                lbl.set_margin_start(8)
                lbl.set_margin_end(8)
                lbl.set_margin_top(4)
                lbl.set_margin_bottom(4)
                self.branch_box.append(lbl)
                self._update_branch_pagination_visibility(False)
                return
            self._cached_branch_names = list(names)
            self._selected_branch_names_for_repo = set(selected_names or [])
            self._hide_branch_loading()
        else:
            self._cached_branch_names.extend(names)
        self._branch_loading_all = has_more
        self._apply_branch_filter_and_page()

    def _get_filtered_branches(self):
        q = (self.branch_search.get_text() or "").strip().lower()
        return [
            n
            for n in self._cached_branch_names
            if not q or q in n.lower()
        ]

    def _apply_branch_filter_and_page(self):
        filtered = self._get_filtered_branches()
        total = len(filtered)
        total_pages = max(
            1, (total + BRANCHES_PER_PAGE - 1) // BRANCHES_PER_PAGE
        )
        self._branch_page = max(1, min(self._branch_page, total_pages))
        start = (self._branch_page - 1) * BRANCHES_PER_PAGE
        page_names = filtered[start : start + BRANCHES_PER_PAGE]
        clear_box(self.branch_box)
        self._branch_checks.clear()

        def make_toggled(name):
            def toggled(cb):
                if cb.get_active():
                    self._selected_branch_names_for_repo.add(name)
                else:
                    self._selected_branch_names_for_repo.discard(name)
            return toggled

        for name in page_names:
            check = Gtk.CheckButton(label=name)
            check.set_margin_start(8)
            check.set_margin_end(8)
            check.set_margin_top(4)
            check.set_margin_bottom(4)
            check.set_active(name in self._selected_branch_names_for_repo)
            check.connect("toggled", make_toggled(name))
            self._branch_checks.append((name, check))
            self.branch_box.append(check)
        loaded = len(self._cached_branch_names)
        loading_hint = " (loading…)" if self._branch_loading_all else ""
        self.branch_page_label.set_text(
            f"Page {self._branch_page} of {total_pages} ({loaded} loaded{loading_hint})"
        )
        if self._branch_loading_all:
            self.branch_spinner.start()
            self.branch_spinner.set_visible(True)
        else:
            self.branch_spinner.stop()
            self.branch_spinner.set_visible(False)
        self._update_branch_pagination_visibility(
            total_pages > 1 or self._branch_loading_all
        )
        self.branch_prev_btn.set_sensitive(self._branch_page > 1)
        self.branch_next_btn.set_sensitive(
            self._branch_page < total_pages
        )
        self.branch_clear_all_btn.set_sensitive(bool(self._selected_full_name))

    def _on_clear_all_branches(self, btn):
        if not self._selected_full_name:
            return
        self._selected_branch_names_for_repo = set()
        self._apply_branch_filter_and_page()

    def _on_branch_search_changed(self, entry):
        if not self._selected_full_name:
            return
        self._branch_page = 1
        self._apply_branch_filter_and_page()

    def _on_branch_prev(self, btn):
        if self._branch_page > 1:
            self._branch_page -= 1
            self._apply_branch_filter_and_page()

    def _on_branch_next(self, btn):
        total_pages = max(
            1,
            (
                len(self._get_filtered_branches()) + BRANCHES_PER_PAGE - 1
            )
            // BRANCHES_PER_PAGE,
        )
        if self._branch_page < total_pages:
            self._branch_page += 1
            self._apply_branch_filter_and_page()

    def apply_selection(self):
        if not self._selected_full_name:
            return
        selected_branches = sorted(self._selected_branch_names_for_repo)
        owner, repo = self._selected_full_name.split("/", 1)
        repo_key = self._selected_full_name
        repos = get_repos(store.config)
        auto_add_pr = self.auto_add_pr_branches_check.get_active()
        if selected_branches:
            existing = next(
                (r for r in repos if r.owner == owner and r.repo == repo),
                None,
            )
            if existing:
                existing.branches = sorted(selected_branches)
                existing.auto_add_pr_branches = auto_add_pr
            else:
                repos.append(
                    RepoConfig(
                        owner=owner,
                        repo=repo,
                        branches=sorted(selected_branches),
                        auto_add_pr_branches=auto_add_pr,
                    )
                )
            set_repos(store.config, repos)
        else:
            set_repos(
                store.config,
                [
                    r
                    for r in repos
                    if r.branches
                    and not (r.owner == owner and r.repo == repo)
                ],
            )
            store.config["watches"] = [
                w
                for w in store.config.get("watches", [])
                if w.get("repo") != repo_key
            ]
            store.config["autoWatches"] = [
                w
                for w in store.config.get("autoWatches", [])
                if w.get("repo") != repo_key
            ]
        save_config(store.config)
