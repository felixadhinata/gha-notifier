#!/usr/bin/env bash
# Wrap an already-built build/linux-unpacked/ into a .deb using plain dpkg-deb —
# no network access needed (unlike electron-builder's deb target, which downloads
# a helper tool called fpm from GitHub releases and can hang behind restrictive
# networks/proxies). Run via `npm run dist` (which builds linux-unpacked first),
# not directly.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

UNPACKED="build/linux-unpacked"
if [ ! -d "$UNPACKED" ]; then
  echo "build/linux-unpacked not found — run 'npm run pack' first (or 'npm run dist')." >&2
  exit 1
fi

VERSION="$(node -p "require('./package.json').version")"
ARCH="amd64"
STAGE="build/deb-stage"
OUT="build/gha-notifier_${VERSION}_${ARCH}.deb"

rm -rf "$STAGE"
mkdir -p "$STAGE/DEBIAN" \
         "$STAGE/opt/gha-notifier" \
         "$STAGE/usr/bin" \
         "$STAGE/usr/share/applications" \
         "$STAGE/usr/share/icons/hicolor/512x512/apps"

cp -r "$UNPACKED"/. "$STAGE/opt/gha-notifier/"

cat > "$STAGE/DEBIAN/control" <<EOF
Package: gha-notifier
Version: $VERSION
Section: utils
Priority: optional
Architecture: $ARCH
Depends: libxss1, xdg-utils, libsecret-1-0
Maintainer: felixadhinata1@gmail.com
Description: GitHub Actions notifier
 Pick the repos you want to monitor; get notified when your own workflow
 runs finish.
EOF

cat > "$STAGE/usr/bin/gha-notifier" <<'EOF'
#!/usr/bin/env bash
exec /opt/gha-notifier/gha-notifier "$@"
EOF
chmod 755 "$STAGE/usr/bin/gha-notifier"

cat > "$STAGE/usr/share/applications/gha-notifier.desktop" <<EOF
[Desktop Entry]
Name=GHA Notifier
Exec=gha-notifier %U
Terminal=false
Type=Application
Icon=gha-notifier
Comment=GitHub Actions notifier: pick repos to monitor, get notified when your own runs finish.
Categories=Utility;
StartupWMClass=GHA Notifier
EOF

cp assets/icon.png "$STAGE/usr/share/icons/hicolor/512x512/apps/gha-notifier.png"

# Update desktop/icon caches after install so the launcher picks it up immediately.
mkdir -p "$STAGE/DEBIAN"
cat > "$STAGE/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database /usr/share/applications 2>/dev/null || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f /usr/share/icons/hicolor 2>/dev/null || true
fi
EOF
chmod 755 "$STAGE/DEBIAN/postinst"

dpkg-deb --build --root-owner-group "$STAGE" "$OUT"
rm -rf "$STAGE"
echo "Built $OUT"
