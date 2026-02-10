# GHA Notifier (GTK)

Native GTK app for GitHub Actions with tray status, branch selection, and workflow alerts.

## Requirements
- Python 3
- GTK 4 + libnotify
- GitHub OAuth App Client ID (Device Flow)

Ubuntu packages:
```bash
sudo apt install python3 python3-gi gir1.2-gtk-4.0 gir1.2-notify-0.7
```
Optional (tray icon on GTK 3 build): `gir1.2-ayatanaappindicator3-0.1`. The app is built for GTK 4; tray icon is not used on GTK 4 (no AppIndicator API).

## Run
```bash
export GHA_NOTIFIER_CLIENT_ID="your_client_id"
./scripts/run.sh
```

## Build .deb
```bash
chmod +x scripts/build-deb.sh
./scripts/build-deb.sh
```

## GTK 4

The app uses GTK 4. The system tray (AppIndicator) is not available on GTK 4, so the app runs as a window-only app; use the window to sign in, pick branches, and manage workflow subscriptions. Notifications still use libnotify.

## Notes
- "My branches" are determined by last commit author matching your GitHub user.
- Tray colors follow priority: red > green > yellow > gray.
