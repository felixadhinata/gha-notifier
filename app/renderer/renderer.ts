export {}; // makes this file a module, so `declare global` below is valid ESM output, not a CommonJS reference

interface GithubRun {
  id: number;
  name: string;
  status: string;
  conclusion: string | null;
  head_branch: string;
  created_at: string;
  run_started_at: string | null;
  updated_at: string;
  html_url: string;
  actor: { login: string } | null;
  head_commit: { message: string } | null;
}

interface GithubUser {
  login: string;
  id: number;
}

type Theme = "system" | "light" | "dark";
type NotificationSound = "none" | "default" | "chime" | "ping" | "bell" | "pop" | "alert";

interface Settings {
  pollIntervalSec: number;
  notifyEnabled: boolean;
  notificationSound: NotificationSound;
  openOnStartup: boolean;
  theme: Theme;
}

/**
 * Mirrors app/preload.ts's GhaApi shape. Duplicated (rather than imported) so this file's
 * TypeScript program never references app/preload.ts — sharing that file across the main
 * (CommonJS) and renderer (ESM) tsc programs causes each to clobber the other's JS output
 * for preload.js.
 */
type SignInResult = { ok: true; user: GithubUser } | { ok: false; error: string };

interface GhaApi {
  getAuthState(): Promise<{ user: GithubUser | null }>;
  signInWithGh(): Promise<SignInResult>;
  signInWithToken(token: string): Promise<SignInResult>;
  signOut(): Promise<{ ok: boolean }>;

  listRepos(): Promise<{ repos: string[]; runsByRepo: Record<string, GithubRun[]> }>;
  addRepo(repoKey: string): Promise<{ added: boolean; repos: string[] }>;
  removeRepo(repoKey: string): Promise<{ removed: boolean; repos: string[] }>;
  refreshRepos(): Promise<{ repos: string[]; runsByRepo: Record<string, GithubRun[]> }>;
  searchMyRepos(): Promise<{ repos: string[] }>;

  getSettings(): Promise<Settings>;
  saveSettings(settings: Settings): Promise<{ ok: boolean }>;
  getVersion(): Promise<string>;
  sendTestNotification(sound: NotificationSound): Promise<{ ok: boolean }>;
  setNotificationSound(sound: NotificationSound): Promise<{ ok: boolean }>;

  getWorkflowFilter(repoKey: string): Promise<{ workflows: string[] }>;
  setWorkflowFilter(repoKey: string, workflows: string[]): Promise<{ ok: boolean }>;

  openExternal(url: string): Promise<void>;
  onRepoRunsUpdated(callback: (runsByRepo: Record<string, GithubRun[]>) => void): void;
  onPlayNotificationSound(callback: (sound: NotificationSound) => void): void;
}

declare global {
  interface Window {
    gha: GhaApi;
  }
}

const gha = window.gha;

let repos: string[] = [];
let runsByRepo: Record<string, GithubRun[]> = {};
let selectedRepo: string | null = null;

// ---------------------------------------------------------------------------
// DOM refs
// ---------------------------------------------------------------------------

const $ = <T extends HTMLElement>(id: string): T => document.getElementById(id) as T;

const avatarEl = $<HTMLDivElement>("avatar");
const authLabelEl = $<HTMLSpanElement>("auth-label");
const settingsBtn = $<HTMLButtonElement>("settings-btn");
const signinScreen = $<HTMLElement>("signin-screen");
const mainView = $<HTMLElement>("main-view");
const signinGhBtn = $<HTMLButtonElement>("signin-gh-btn");
const signinTokenBtn = $<HTMLButtonElement>("signin-token-btn");
const signinStatus = $<HTMLDivElement>("signin-status");

const repoListEl = $<HTMLUListElement>("repo-list");
const reposSpinner = $<HTMLDivElement>("repos-spinner");
const addRepoBtn = $<HTMLButtonElement>("add-repo-btn");
const runsTitle = $<HTMLHeadingElement>("runs-title");
runsTitle.addEventListener("click", (e) => {
  const link = (e.target as HTMLElement).closest(".repo-link");
  if (!link || !selectedRepo) return;
  e.preventDefault();
  void gha.openExternal(`https://github.com/${selectedRepo}`);
});
const runsBody = $<HTMLDivElement>("runs-body");
const refreshBtn = $<HTMLButtonElement>("refresh-btn");

const workflowFilterBtn = $<HTMLButtonElement>("workflow-filter-btn");
const workflowFilterPopover = $<HTMLDivElement>("workflow-filter-popover");
const workflowFilterPillbox = $<HTMLDivElement>("workflow-filter-pillbox");
const workflowFilterTrigger = $<HTMLButtonElement>("workflow-filter-trigger");
const workflowFilterOptions = $<HTMLUListElement>("workflow-filter-options");

const runsFiltersEl = $<HTMLDivElement>("runs-filters");
const filterWorkflowEl = $<HTMLInputElement>("filter-workflow");
const filterBranchEl = $<HTMLInputElement>("filter-branch");
const filterStatusEl = $<HTMLSelectElement>("filter-status");
const filterCommitEl = $<HTMLInputElement>("filter-commit");

const paginationEl = $<HTMLDivElement>("runs-pagination");
const pagePrevBtn = $<HTMLButtonElement>("page-prev");
const pageNextBtn = $<HTMLButtonElement>("page-next");
const pageLabelEl = $<HTMLSpanElement>("page-label");

const RUNS_PAGE_SIZE = 15;
let currentPage = 1;

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

function initials(login: string): string {
  return (login[0] || "?").toUpperCase();
}

function renderAuth(user: { login: string } | null): void {
  if (user) {
    avatarEl.textContent = initials(user.login);
    avatarEl.hidden = false;
    authLabelEl.textContent = `Signed in as ${user.login}`;
    settingsBtn.hidden = false;
    signinScreen.hidden = true;
    mainView.hidden = false;
  } else {
    avatarEl.hidden = true;
    authLabelEl.textContent = "Sign in to get started";
    settingsBtn.hidden = true;
    signinScreen.hidden = false;
    mainView.hidden = true;
  }
}

signinGhBtn.addEventListener("click", async () => {
  setSigninLoading(true, "Getting token from gh…");
  const result = await gha.signInWithGh();
  setSigninLoading(false);
  if (!result.ok) {
    signinStatus.textContent = result.error || "Sign-in failed.";
    return;
  }
  signinStatus.textContent = "";
  renderAuth(result.user);
  void loadRepos();
});

function setSigninLoading(loading: boolean, message = ""): void {
  signinGhBtn.disabled = loading;
  signinTokenBtn.disabled = loading;
  signinStatus.textContent = message;
}

// ---------------------------------------------------------------------------
// Repos pane
// ---------------------------------------------------------------------------

function statusClass(status: "yellow" | "green" | "red" | "gray"): string {
  return { yellow: "running", green: "success", red: "fail", gray: "idle" }[status];
}

function repoStatus(runs: GithubRun[] | undefined): "yellow" | "green" | "red" | "gray" {
  if (!runs || runs.length === 0) return "gray";
  const inProgress = runs.some((r) => ["in_progress", "queued"].includes((r.status || "").toLowerCase()));
  if (inProgress) return "yellow";
  const top = runs[0];
  if (top.status === "completed") return top.conclusion === "success" ? "green" : "red";
  return "gray";
}

function renderRepoList(): void {
  repoListEl.innerHTML = "";
  for (const repoKey of repos) {
    const li = document.createElement("li");
    li.className = `repo-item${repoKey === selectedRepo ? " selected" : ""}`;

    const dot = document.createElement("span");
    dot.className = `dot ${statusClass(repoStatus(runsByRepo[repoKey]))}`;

    const name = document.createElement("span");
    name.className = "repo-name";
    const [owner, repoName] = repoKey.split("/", 2);
    name.innerHTML = repoName
      ? `<span class="repo-owner">${escapeHtml(owner)}/</span>${escapeHtml(repoName)}`
      : escapeHtml(repoKey);

    const removeBtn = document.createElement("button");
    removeBtn.className = "remove-btn";
    removeBtn.title = "Stop monitoring this repository";
    removeBtn.textContent = "−";
    removeBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      void onRemoveRepo(repoKey);
    });

    li.append(dot, name, removeBtn);
    li.addEventListener("click", () => void selectRepo(repoKey));
    repoListEl.appendChild(li);
  }
}

/** Select a repo, resetting per-repo UI state and (re-)loading its workflow notification filter. */
async function selectRepo(repoKey: string): Promise<void> {
  if (selectedRepo === repoKey) return;
  selectedRepo = repoKey;
  currentPage = 1;
  clearFilters();
  workflowFilterPopover.hidden = true;
  workflowFilterRepo = repoKey;
  workflowFilterSelected = [];
  renderRepoList();
  renderRunsPane();
  const result = await gha.getWorkflowFilter(repoKey);
  if (workflowFilterRepo !== repoKey) return; // selection changed again before this resolved
  workflowFilterSelected = result.workflows;
  renderRunsPane();
}

async function onRemoveRepo(repoKey: string): Promise<void> {
  const result = await gha.removeRepo(repoKey);
  repos = result.repos;
  if (selectedRepo === repoKey) {
    selectedRepo = null;
    currentPage = 1;
    clearFilters();
    workflowFilterPopover.hidden = true;
    workflowFilterRepo = null;
    workflowFilterSelected = [];
  }
  delete runsByRepo[repoKey];
  renderRepoList();
  renderRunsPane();
}

async function loadRepos(): Promise<void> {
  reposSpinner.hidden = false;
  const result = await gha.listRepos();
  repos = result.repos;
  runsByRepo = result.runsByRepo;
  reposSpinner.hidden = true;
  renderRepoList();
  renderRunsPane();
}

refreshBtn.addEventListener("click", async () => {
  reposSpinner.hidden = false;
  const result = await gha.refreshRepos();
  repos = result.repos;
  runsByRepo = result.runsByRepo;
  reposSpinner.hidden = true;
  renderRepoList();
  renderRunsPane();
});

gha.onRepoRunsUpdated((updated: Record<string, GithubRun[]>) => {
  runsByRepo = updated;
  renderRepoList();
  renderRunsPane();
});

// ---------------------------------------------------------------------------
// Runs pane
// ---------------------------------------------------------------------------

function formatDuration(startedAt: string | null, updatedAt: string | null): string {
  if (!startedAt) return "—";
  const start = Date.parse(startedAt);
  if (Number.isNaN(start)) return "—";
  const end = updatedAt ? Date.parse(updatedAt) : Date.now();
  const seconds = Math.max(0, Math.round((end - start) / 1000));
  const minutes = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return minutes === 0 ? `${secs}s` : `${minutes}m ${secs}s`;
}

function formatAbsolute(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function formatRelative(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  const now = new Date();
  const diffSec = Math.floor((now.getTime() - date.getTime()) / 1000);
  if (diffSec < 60) return "just now";
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin} min ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (date.toDateString() === now.toDateString()) return `${diffHr} hr ago`;
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (date.toDateString() === yesterday.toDateString()) return "Yesterday";
  const diffDays = Math.floor(diffHr / 24);
  if (diffDays < 7) return `${diffDays} day${diffDays === 1 ? "" : "s"} ago`;
  return formatAbsolute(iso);
}

// ---------------------------------------------------------------------------
// Filters + pagination
// ---------------------------------------------------------------------------

function clearFilters(): void {
  filterWorkflowEl.value = "";
  filterBranchEl.value = "";
  filterStatusEl.value = "";
  filterCommitEl.value = "";
}

function applyFilters(runs: GithubRun[]): GithubRun[] {
  const workflowQ = filterWorkflowEl.value.trim().toLowerCase();
  const branchQ = filterBranchEl.value.trim().toLowerCase();
  const statusQ = filterStatusEl.value; // "" | "running" | "success" | "fail"
  const commitQ = filterCommitEl.value.trim().toLowerCase();

  const notifyFilter = workflowFilterRepo === selectedRepo ? workflowFilterSelected : [];

  return runs.filter((run) => {
    if (workflowQ && !(run.name || "").toLowerCase().includes(workflowQ)) return false;
    if (branchQ && !(run.head_branch || "").toLowerCase().includes(branchQ)) return false;
    if (statusQ && statusClass(repoStatus([run])) !== statusQ) return false;
    if (commitQ && !(run.head_commit?.message || "").toLowerCase().includes(commitQ)) return false;
    if (notifyFilter.length > 0 && !notifyFilter.includes(run.name || "Workflow")) return false;
    return true;
  });
}

for (const el of [filterWorkflowEl, filterBranchEl, filterCommitEl]) {
  el.addEventListener("input", () => {
    currentPage = 1;
    renderRunsPane();
  });
}
filterStatusEl.addEventListener("change", () => {
  currentPage = 1;
  renderRunsPane();
});

pagePrevBtn.addEventListener("click", () => {
  currentPage = Math.max(1, currentPage - 1);
  renderRunsPane();
});
pageNextBtn.addEventListener("click", () => {
  currentPage += 1;
  renderRunsPane();
});

function renderRunsPane(): void {
  refreshBtn.disabled = selectedRepo === null;
  workflowFilterBtn.disabled = selectedRepo === null;
  runsBody.innerHTML = "";

  if (selectedRepo === null) {
    runsTitle.textContent = "";
    runsFiltersEl.hidden = true;
    paginationEl.hidden = true;
    runsBody.appendChild(
      emptyPane("\u{1F441}", "Select a repository", "Pick one on the left to see your recent workflow runs."),
    );
    return;
  }

  runsTitle.innerHTML = `<a href="#" class="repo-link">${escapeHtml(selectedRepo)}</a> <span class="sub">— your runs, all branches</span>`;
  const runs = runsByRepo[selectedRepo];

  if (runs === undefined) {
    runsFiltersEl.hidden = true;
    paginationEl.hidden = true;
    const loading = document.createElement("div");
    loading.className = "plain-message";
    loading.textContent = "Loading…";
    runsBody.appendChild(loading);
    return;
  }
  if (runs.length === 0) {
    runsFiltersEl.hidden = true;
    paginationEl.hidden = true;
    const msg = document.createElement("div");
    msg.className = "plain-message";
    msg.textContent = "No workflow runs found for you in this repository.";
    runsBody.appendChild(msg);
    return;
  }

  runsFiltersEl.hidden = false;
  const filtered = applyFilters(runs);

  if (filtered.length === 0) {
    paginationEl.hidden = true;
    const msg = document.createElement("div");
    msg.className = "plain-message";
    msg.textContent = "No runs match these filters.";
    runsBody.appendChild(msg);
    return;
  }

  const totalPages = Math.max(1, Math.ceil(filtered.length / RUNS_PAGE_SIZE));
  currentPage = Math.min(currentPage, totalPages);
  const start = (currentPage - 1) * RUNS_PAGE_SIZE;
  const pageRuns = filtered.slice(start, start + RUNS_PAGE_SIZE);

  const table = buildRunsTable(pageRuns);
  runsBody.appendChild(table);
  attachColumnResize(table);

  paginationEl.hidden = totalPages <= 1;
  pagePrevBtn.disabled = currentPage <= 1;
  pageNextBtn.disabled = currentPage >= totalPages;
  pageLabelEl.textContent = `Page ${currentPage} of ${totalPages} (${filtered.length} runs)`;
}

function emptyPane(mark: string, title: string, description: string): HTMLElement {
  const box = document.createElement("div");
  box.className = "empty-pane";
  const markEl = document.createElement("div");
  markEl.className = "mark";
  markEl.textContent = mark;
  const p = document.createElement("p");
  p.innerHTML = `<b>${escapeHtml(title)}</b><br>${escapeHtml(description)}`;
  box.append(markEl, p);
  return box;
}

const RESIZABLE_COLUMNS = ["workflow", "branch", "status", "duration", "commit", "startedAt", "triggered"] as const;
type ColumnKey = (typeof RESIZABLE_COLUMNS)[number];
/** Session-only: widths the user has dragged, keyed by column. Re-applied on every rebuild
 * (filters/pagination/polling all rebuild the table) so a resize sticks until sign-out. */
const columnWidths: Partial<Record<ColumnKey, number>> = {};

function buildRunsTable(runs: GithubRun[]): HTMLTableElement {
  const table = document.createElement("table");
  table.className = "runs";
  table.innerHTML = `
    <colgroup>
      <col data-col="workflow" />
      <col data-col="branch" />
      <col data-col="status" />
      <col data-col="duration" />
      <col data-col="commit" />
      <col data-col="startedAt" />
      <col data-col="triggered" />
      <col data-col="open" />
    </colgroup>
    <thead>
      <tr>
        <th data-col="workflow">Workflow<span class="col-resize-handle"></span></th>
        <th data-col="branch">Branch<span class="col-resize-handle"></span></th>
        <th data-col="status">Status<span class="col-resize-handle"></span></th>
        <th class="num" data-col="duration">Duration<span class="col-resize-handle"></span></th>
        <th data-col="commit">Commit<span class="col-resize-handle"></span></th>
        <th class="num" data-col="startedAt">Started At<span class="col-resize-handle"></span></th>
        <th class="num" data-col="triggered">Triggered<span class="col-resize-handle"></span></th>
        <th></th>
      </tr>
    </thead>
  `;
  for (const col of table.querySelectorAll<HTMLTableColElement>("col")) {
    const key = col.dataset.col as ColumnKey | "open";
    const width = key !== "open" ? columnWidths[key] : undefined;
    if (width) col.style.width = `${width}px`;
  }
  const tbody = document.createElement("tbody");
  table.appendChild(tbody);
  for (const run of runs) {
    const tr = document.createElement("tr");
    const inProgress = ["in_progress", "queued"].includes((run.status || "").toLowerCase());
    const status = repoStatus([run]);
    const statusText = { yellow: "Running", green: "Success", red: "Failed", gray: "—" }[status];
    const commit = (run.head_commit?.message || "").trim().split("\n")[0].slice(0, 80) || "—";

    tr.innerHTML = `
      <td>${escapeHtml(run.name || "Workflow")}</td>
      <td>${escapeHtml(run.head_branch || "—")}</td>
      <td><span class="status-pill ${statusClass(status)}"><span class="dot ${statusClass(status)}"></span>${statusText}</span></td>
      <td class="num">${escapeHtml(formatDuration(run.run_started_at, inProgress ? null : run.updated_at))}</td>
      <td><span class="commit-cell" title="${escapeHtml(commit)}">${escapeHtml(commit)}</span></td>
      <td class="num">${escapeHtml(formatAbsolute(run.run_started_at))}</td>
      <td class="num">${escapeHtml(formatRelative(run.created_at))}</td>
      <td></td>
    `;
    const openCell = tr.lastElementChild as HTMLTableCellElement;
    if (run.html_url) {
      const link = document.createElement("a");
      link.href = "#";
      link.className = "open-link";
      link.textContent = "Open ↗";
      link.addEventListener("click", (e) => {
        e.preventDefault();
        void gha.openExternal(run.html_url);
      });
      openCell.appendChild(link);
    }
    tbody.appendChild(tr);
  }
  return table;
}

let columnWidthsCaptured = false;

/**
 * Wires up drag-to-resize handles on the header cells. The table starts in normal
 * auto-layout (so columns size to content, same as before); the very first time this
 * runs, it snapshots those natural widths into columnWidths and switches to a fixed
 * layout so resizing has something stable to adjust. Every rebuild after that (every
 * poll/filter/page change creates a fresh <table>) re-applies the saved widths via the
 * colgroup built in buildRunsTable, so a resize persists for the rest of the session.
 */
function attachColumnResize(table: HTMLTableElement): void {
  const ths = [...table.querySelectorAll<HTMLTableCellElement>("thead th[data-col]")];
  const cols = [...table.querySelectorAll<HTMLTableColElement>("col")];

  if (!columnWidthsCaptured) {
    for (const th of ths) {
      const key = th.dataset.col as ColumnKey;
      columnWidths[key] = th.getBoundingClientRect().width;
    }
    columnWidthsCaptured = true;
    for (const col of cols) {
      const key = col.dataset.col as ColumnKey | "open";
      if (key !== "open") col.style.width = `${columnWidths[key]}px`;
    }
  }
  table.style.tableLayout = "fixed";

  for (const th of ths) {
    const handle = th.querySelector<HTMLElement>(".col-resize-handle");
    const key = th.dataset.col as ColumnKey;
    const col = cols.find((c) => c.dataset.col === key);
    if (!handle || !col) continue;
    handle.addEventListener("mousedown", (e) => {
      e.preventDefault();
      const startX = e.clientX;
      const startWidth = col.getBoundingClientRect().width;
      handle.classList.add("resizing");
      const onMove = (moveEvent: MouseEvent) => {
        const next = Math.max(50, startWidth + (moveEvent.clientX - startX));
        columnWidths[key] = next;
        col.style.width = `${next}px`;
      };
      const onUp = () => {
        handle.classList.remove("resizing");
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
      };
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    });
  }
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

// ---------------------------------------------------------------------------
// Add-repository popover
// ---------------------------------------------------------------------------

const addRepoPopover = $<HTMLDivElement>("add-repo-popover");
const addRepoInput = $<HTMLInputElement>("add-repo-input");
const addRepoSuggestions = $<HTMLUListElement>("add-repo-suggestions");
const addRepoHint = $<HTMLParagraphElement>("add-repo-hint");
const addRepoConfirm = $<HTMLButtonElement>("add-repo-confirm");

let myRepos: string[] = [];
let activatedRepo: string | null = null;

addRepoBtn.addEventListener("click", async (e) => {
  e.stopPropagation();
  if (!addRepoPopover.hidden) {
    addRepoPopover.hidden = true;
    return;
  }
  activatedRepo = null;
  addRepoInput.value = "";
  addRepoConfirm.disabled = true;
  addRepoHint.textContent = "Loading your repositories…";
  addRepoSuggestions.innerHTML = "";
  addRepoPopover.hidden = false;
  addRepoInput.focus();
  const result = await gha.searchMyRepos();
  myRepos = result.repos;
  addRepoHint.textContent = 'Select a repository, or type "owner/repo" above and press Enter.';
  refillSuggestions();
});

addRepoPopover.querySelectorAll<HTMLButtonElement>('[data-action="cancel"]').forEach((btn) => {
  btn.addEventListener("click", () => {
    addRepoPopover.hidden = true;
  });
});
addRepoPopover.addEventListener("click", (e) => e.stopPropagation());
document.addEventListener("click", () => {
  addRepoPopover.hidden = true;
});

addRepoInput.addEventListener("input", () => {
  activatedRepo = null;
  refillSuggestions();
});

addRepoInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && getSelectedRepo()) {
    e.preventDefault();
    void confirmAddRepo();
  }
});

addRepoConfirm.addEventListener("click", () => void confirmAddRepo());

function refillSuggestions(): void {
  const query = addRepoInput.value.trim().toLowerCase();
  addRepoSuggestions.innerHTML = "";
  for (const name of myRepos) {
    if (repos.includes(name)) continue;
    if (query && !name.toLowerCase().includes(query)) continue;
    const li = document.createElement("li");
    li.textContent = name;
    li.addEventListener("click", () => {
      activatedRepo = name;
      addRepoConfirm.disabled = false;
      void confirmAddRepo();
    });
    addRepoSuggestions.appendChild(li);
  }
  addRepoConfirm.disabled = !getSelectedRepo();
}

function getSelectedRepo(): string | null {
  if (activatedRepo) return activatedRepo;
  const text = addRepoInput.value.trim();
  const [owner, repo] = text.split("/", 2);
  return owner && repo ? text : null;
}

async function confirmAddRepo(): Promise<void> {
  const repoKey = getSelectedRepo();
  if (!repoKey) return;
  addRepoPopover.hidden = true;
  const result = await gha.addRepo(repoKey);
  if (!result.added) return;
  repos = result.repos;
  renderRepoList();
  const refreshed = await gha.refreshRepos();
  repos = refreshed.repos;
  runsByRepo = refreshed.runsByRepo;
  renderRepoList();
  renderRunsPane();
}

// ---------------------------------------------------------------------------
// Workflow notification-filter popover
// ---------------------------------------------------------------------------

let workflowFilterRepo: string | null = null;
let workflowFilterSelected: string[] = [];

function distinctWorkflowNames(repoKey: string): string[] {
  const names = new Set((runsByRepo[repoKey] || []).map((r) => r.name || "Workflow"));
  return Array.from(names).sort();
}

function renderWorkflowFilterOptions(): void {
  const available = distinctWorkflowNames(workflowFilterRepo || "").filter(
    (name) => !workflowFilterSelected.includes(name),
  );
  workflowFilterOptions.innerHTML = "";
  for (const name of available) {
    const li = document.createElement("li");
    li.textContent = name;
    li.addEventListener("click", () => {
      workflowFilterSelected.push(name);
      workflowFilterOptions.hidden = true;
      void saveWorkflowFilter();
    });
    workflowFilterOptions.appendChild(li);
  }
}

function renderWorkflowFilterPillbox(): void {
  workflowFilterPillbox.querySelectorAll(".pill").forEach((el) => {
    el.remove();
  });
  for (const name of workflowFilterSelected) {
    const pill = document.createElement("span");
    pill.className = "pill";
    const label = document.createElement("span");
    label.textContent = name;
    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "pill-remove";
    removeBtn.title = `Stop notifying for ${name}`;
    removeBtn.textContent = "×";
    removeBtn.addEventListener("click", () => {
      workflowFilterSelected = workflowFilterSelected.filter((n) => n !== name);
      void saveWorkflowFilter();
    });
    pill.append(label, removeBtn);
    workflowFilterPillbox.insertBefore(pill, workflowFilterTrigger);
  }
  renderWorkflowFilterOptions();
}

async function saveWorkflowFilter(): Promise<void> {
  if (!workflowFilterRepo) return;
  renderWorkflowFilterPillbox();
  currentPage = 1;
  renderRunsPane();
  await gha.setWorkflowFilter(workflowFilterRepo, workflowFilterSelected);
}

workflowFilterTrigger.addEventListener("click", () => {
  workflowFilterOptions.hidden = !workflowFilterOptions.hidden;
  if (!workflowFilterOptions.hidden) renderWorkflowFilterOptions();
});

workflowFilterBtn.addEventListener("click", (e) => {
  e.stopPropagation();
  if (!workflowFilterPopover.hidden) {
    workflowFilterPopover.hidden = true;
    return;
  }
  if (!selectedRepo) return;
  workflowFilterOptions.hidden = true;
  renderWorkflowFilterPillbox();
  workflowFilterPopover.hidden = false;
});

workflowFilterPopover.addEventListener("click", (e) => e.stopPropagation());
document.addEventListener("click", () => {
  workflowFilterPopover.hidden = true;
  workflowFilterOptions.hidden = true;
});

// ---------------------------------------------------------------------------
// Sign-in with token modal
// ---------------------------------------------------------------------------

const tokenModal = $<HTMLDivElement>("token-modal");
const tokenInput = $<HTMLInputElement>("token-input");
const tokenConfirm = $<HTMLButtonElement>("token-confirm");
const tokenLink = $<HTMLAnchorElement>("token-link");

tokenLink.addEventListener("click", (e) => {
  e.preventDefault();
  void gha.openExternal(
    "https://github.com/settings/tokens/new?scopes=repo,workflow,read:user&description=GHA+Notifier",
  );
});

signinTokenBtn.addEventListener("click", () => {
  tokenInput.value = "";
  openModal(tokenModal);
  tokenInput.focus();
});

tokenConfirm.addEventListener("click", async () => {
  const token = tokenInput.value.trim();
  if (!token) return;
  closeModal(tokenModal);
  setSigninLoading(true, "Checking token…");
  const result = await gha.signInWithToken(token);
  setSigninLoading(false);
  if (!result.ok) {
    signinStatus.textContent = `Sign-in failed: ${result.error}`;
    return;
  }
  signinStatus.textContent = "";
  renderAuth(result.user);
  void loadRepos();
});

// ---------------------------------------------------------------------------
// Settings modal
// ---------------------------------------------------------------------------

const settingsModal = $<HTMLDivElement>("settings-modal");
const settingsInterval = $<HTMLInputElement>("settings-interval");
const settingsNotify = $<HTMLInputElement>("settings-notify");
const settingsStartup = $<HTMLInputElement>("settings-startup");
const settingsConfirm = $<HTMLButtonElement>("settings-confirm");
const settingsTheme = $<HTMLSelectElement>("settings-theme");
const settingsSound = $<HTMLSelectElement>("settings-sound");
const settingsSignout = $<HTMLButtonElement>("settings-signout");
const testNotificationRow = $<HTMLDivElement>("test-notification-row");
const testNotificationBtn = $<HTMLButtonElement>("test-notification-btn");
const appVersionEl = $<HTMLSpanElement>("app-version");

function updateTestNotificationVisibility(): void {
  testNotificationRow.hidden = !settingsNotify.checked;
}

settingsNotify.addEventListener("change", updateTestNotificationVisibility);

// Saved the moment it's picked, independent of Apply — otherwise closing the modal via
// Cancel/backdrop-click silently discards the choice, even though the test button next
// to it always plays whatever's currently selected (making that look "applied" too).
settingsSound.addEventListener("change", () => {
  void gha.setNotificationSound(settingsSound.value as NotificationSound);
});

function applyTheme(theme: Theme): void {
  if (theme === "system") {
    delete document.documentElement.dataset.theme;
  } else {
    document.documentElement.dataset.theme = theme;
  }
}

const SOUND_FILES: Record<Exclude<NotificationSound, "none">, string> = {
  default: "sounds/default.wav",
  chime: "sounds/chime.wav",
  ping: "sounds/ping.wav",
  bell: "sounds/bell.wav",
  pop: "sounds/pop.wav",
  alert: "sounds/alert.wav",
};

function playNotificationSound(sound: NotificationSound): void {
  if (sound === "none") return;
  new Audio(SOUND_FILES[sound]).play().catch(() => {});
}

gha.onPlayNotificationSound(playNotificationSound);

settingsBtn.addEventListener("click", async () => {
  const settings = await gha.getSettings();
  settingsInterval.value = String(settings.pollIntervalSec);
  settingsNotify.checked = settings.notifyEnabled;
  settingsStartup.checked = settings.openOnStartup;
  settingsTheme.value = settings.theme;
  settingsSound.value = settings.notificationSound;
  updateTestNotificationVisibility();
  openModal(settingsModal);
});

settingsConfirm.addEventListener("click", async () => {
  const theme = settingsTheme.value as Theme;
  await gha.saveSettings({
    pollIntervalSec: Math.max(10, Number(settingsInterval.value) || 20),
    notifyEnabled: settingsNotify.checked,
    notificationSound: settingsSound.value as NotificationSound,
    openOnStartup: settingsStartup.checked,
    theme,
  });
  applyTheme(theme);
  closeModal(settingsModal);
});

testNotificationBtn.addEventListener("click", async () => {
  testNotificationBtn.disabled = true;
  const originalText = testNotificationBtn.textContent;
  await gha.sendTestNotification(settingsSound.value as NotificationSound);
  testNotificationBtn.textContent = "Sent!";
  setTimeout(() => {
    testNotificationBtn.textContent = originalText;
    testNotificationBtn.disabled = false;
  }, 1500);
});

settingsSignout.addEventListener("click", async () => {
  closeModal(settingsModal);
  await gha.signOut();
  repos = [];
  runsByRepo = {};
  selectedRepo = null;
  currentPage = 1;
  clearFilters();
  renderAuth(null);
});

// ---------------------------------------------------------------------------
// Modal plumbing
// ---------------------------------------------------------------------------

function openModal(modal: HTMLElement): void {
  modal.hidden = false;
}
function closeModal(modal: HTMLElement): void {
  modal.hidden = true;
}
document.querySelectorAll<HTMLElement>(".modal-backdrop").forEach((backdrop) => {
  backdrop.addEventListener("click", (e) => {
    if (e.target === backdrop) closeModal(backdrop);
  });
  backdrop.querySelectorAll<HTMLButtonElement>('[data-action="cancel"]').forEach((btn) => {
    btn.addEventListener("click", () => closeModal(backdrop));
  });
});

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

(async function init() {
  const [{ user }, settings, version] = await Promise.all([gha.getAuthState(), gha.getSettings(), gha.getVersion()]);
  applyTheme(settings.theme);
  renderAuth(user);
  if (user) void loadRepos();
  appVersionEl.textContent = `GHA Notifier v${version}`;
})();
