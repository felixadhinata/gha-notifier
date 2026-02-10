#!/usr/bin/env bash
set -euo pipefail

APP_NAME="gha-notifier"
VERSION="0.1.0"
BUILD_DIR="$(pwd)/build/deb"

rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR/DEBIAN"
mkdir -p "$BUILD_DIR/opt/$APP_NAME"
mkdir -p "$BUILD_DIR/usr/bin"
mkdir -p "$BUILD_DIR/usr/share/applications"
mkdir -p "$BUILD_DIR/usr/share/icons/hicolor/scalable/apps"

cat > "$BUILD_DIR/DEBIAN/control" <<EOF
Package: $APP_NAME
Version: $VERSION
Section: utils
Priority: optional
Architecture: all
Maintainer: GHA Notifier
Depends: python3, python3-gi, gir1.2-gtk-4.0, gir1.2-notify-0.7
Description: GitHub Actions notifier with native GTK UI.
EOF

cat > "$BUILD_DIR/usr/bin/$APP_NAME" <<'EOF'
#!/usr/bin/env bash
PYTHONPATH="/opt/gha-notifier/src" exec python3 -m app
EOF
chmod +x "$BUILD_DIR/usr/bin/$APP_NAME"

# Desktop file must match app's application_id (com.gha.notifier) so the dock shows correct icon and name
cat > "$BUILD_DIR/usr/share/applications/com.gha.notifier.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=GHA Notifier
Comment=GitHub Actions workflow status notifier with system tray
Exec=$APP_NAME
Icon=$APP_NAME
StartupWMClass=com.gha.notifier
Categories=Utility;Development;
Keywords=github;actions;workflow;notifier;tray;
StartupNotify=true
EOF

# Post-install: update desktop and icon caches so the app shows in the menu
cat > "$BUILD_DIR/DEBIAN/postinst" <<'POSTINST'
#!/bin/sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database /usr/share/applications 2>/dev/null || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f /usr/share/icons/hicolor 2>/dev/null || true
fi
POSTINST
chmod 755 "$BUILD_DIR/DEBIAN/postinst"

cp -r src assets "$BUILD_DIR/opt/$APP_NAME/"
# App icon for launcher and desktop (same design as tray icons)
cp assets/icon.svg "$BUILD_DIR/usr/share/icons/hicolor/scalable/apps/$APP_NAME.svg"

dpkg-deb --build "$BUILD_DIR" "$(dirname "$BUILD_DIR")/gha-notifier.deb"
