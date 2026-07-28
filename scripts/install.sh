#!/usr/bin/env bash
# Build and install GHA Notifier as a .deb on this machine.
# Run from inside the repo (where you already have it checked out):
#   ./scripts/install.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ ! -f package.json ] || ! grep -q '"name": "gha-notifier"' package.json; then
  echo "Run this from inside the gha-notifier repo (scripts/install.sh)." >&2
  exit 1
fi

if ! command -v node &> /dev/null; then
  echo "Node.js 18+ is required. Install it, e.g.:" >&2
  echo "  curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - && sudo apt install -y nodejs" >&2
  exit 1
fi

NODE_MAJOR="$(node -v | sed -E 's/^v([0-9]+).*/\1/')"
if [ "$NODE_MAJOR" -lt 18 ]; then
  echo "Node.js 18+ required, found $(node -v)." >&2
  exit 1
fi

if ! command -v dpkg &> /dev/null; then
  echo "dpkg not found — this script installs a .deb, which needs a Debian/Ubuntu-based system." >&2
  echo "On another distro, build and run without packaging instead:" >&2
  echo "  npm install && npm start" >&2
  exit 1
fi

echo "==> Installing npm dependencies"
npm install

echo "==> Building the .deb package"
rm -rf build dist
npm run dist

DEB_FILE="$(ls build/gha-notifier_*_amd64.deb 2>/dev/null | head -1)"
if [ -z "$DEB_FILE" ]; then
  echo "Build finished but no .deb was found in build/." >&2
  exit 1
fi

echo "==> Installing $DEB_FILE (requires sudo)"
if ! sudo dpkg -i "$DEB_FILE"; then
  echo "==> Resolving missing dependencies"
  sudo apt-get install -f -y
fi

echo ""
echo "Done. Launch it with: gha-notifier"
echo "Sign in with 'gh auth login' beforehand, or paste a personal access token in the app."
