#!/usr/bin/env bash
# Tag the current version, push the tag, build the .deb, and publish a GitHub
# release with the .deb attached. Run this on your own machine (needs the gh
# CLI, authenticated) — it can't be run from the sandbox that generated it,
# since that session's git remote rejects tag pushes and has no release API
# access.
#
# Usage: bash scripts/publish-release.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if ! command -v gh >/dev/null 2>&1; then
  echo "gh (GitHub CLI) is required. Install it: https://cli.github.com/" >&2
  exit 1
fi
if ! gh auth status >/dev/null 2>&1; then
  echo "gh is not authenticated. Run: gh auth login" >&2
  exit 1
fi

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [ "$BRANCH" != "main" ]; then
  echo "You're on '$BRANCH', not 'main'. Switch to main first: git checkout main && git pull" >&2
  exit 1
fi
if [ -n "$(git status --porcelain)" ]; then
  echo "Working tree has uncommitted changes. Commit or stash first." >&2
  exit 1
fi

git fetch origin main
if [ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main)" ]; then
  echo "Local main is not in sync with origin/main. Run: git pull origin main" >&2
  exit 1
fi

VERSION="$(node -p "require('./package.json').version")"
TAG="v${VERSION}"

if git rev-parse "$TAG" >/dev/null 2>&1; then
  echo "Tag $TAG already exists locally."
else
  git tag -a "$TAG" -m "$TAG"
  echo "Created tag $TAG"
fi

if git ls-remote --tags origin "refs/tags/$TAG" | grep -q "$TAG"; then
  echo "Tag $TAG already exists on origin, skipping push."
else
  git push origin "$TAG"
  echo "Pushed tag $TAG"
fi

echo "==> Building .deb (this runs the full pack + package step, may take a few minutes)"
npm run dist

DEB_PATH="build/gha-notifier_${VERSION}_amd64.deb"
if [ ! -f "$DEB_PATH" ]; then
  echo "Expected $DEB_PATH but it wasn't produced by the build." >&2
  exit 1
fi

NOTES="GHA Notifier ${VERSION}: Electron + TypeScript rewrite of the repo-only workflow-run notifier — auto-watch runs you triggered, tray notifications with a watch list, runs table with pagination/filters, System/Light/Dark theme, Biome-linted CI. See the .deb asset below to install.

New in 2.2.1:
- Fixed the tray icon visibly flickering every poll cycle by only re-setting it when the status color actually changes
- Tray menu entries now show each run's duration alongside the branch
- Runs table columns are now drag-resizable, with widths persisting for the session across polls/filters/pagination
- Settings: sound picker now sits before \"Send test notification\" with a fixed width so its layout doesn't shift when the button's label changes; both are hidden together when desktop notifications are disabled

New in 2.2.0:
- Tray menu (and icon color) now respects the workflow notification filter, instead of tracking every run regardless of subscription
- Fixed the tray's popup menu closing itself every ~10s while open, and submenu flyouts (a repo's run list) closing prematurely on top of that
- Settings has a \"Send test notification\" button so you can verify notifications work without waiting for a real run
- Notification sound is now app-controlled (bundled tones played directly), with 7 options: No sound, Default, Chime, Ping, Bell, Pop, Alert — reliable regardless of the desktop's own notification-sound config

New in 2.1.0:
- Per-repo workflow notification filter: pick which workflows to get desktop notifications for (pillbox + themed dropdown next to Refresh); leave empty to notify for all
- The runs table now filters by the same selected workflows, live
- Repo title in the runs pane links out to the repo on GitHub
- Open-on-startup now defaults on for new installs"

if gh release view "$TAG" >/dev/null 2>&1; then
  echo "Release $TAG already exists, uploading .deb to it."
  gh release upload "$TAG" "$DEB_PATH" --clobber
else
  gh release create "$TAG" "$DEB_PATH" --title "$TAG" --notes "$NOTES"
fi

echo "Done: https://github.com/$(gh repo view --json nameWithOwner -q .nameWithOwner)/releases/tag/${TAG}"
