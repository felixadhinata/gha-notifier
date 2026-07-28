# GHA Notifier

Desktop app for GitHub Actions (Electron + TypeScript). Pick the repositories you want to
monitor; it watches workflow runs you triggered or committed, across every branch, shows
them in a tray icon, and notifies you when they finish.

## Requirements
- Node.js 18+ and npm
- Linux runtime libraries (installed automatically as `.deb` dependencies): `libxss1`,
  `xdg-utils`, `libsecret-1-0`
- A `gh` CLI login, or a GitHub personal access token (scopes: `repo`, `workflow`, `read:user`)

## Develop
```bash
npm install
npm start        # builds and launches the app
```

## Build a `.deb`
```bash
npm install
npm run dist
sudo dpkg -i build/gha-notifier_*_amd64.deb
```

## Project layout
- `app/main/` — main process: config, GitHub API client, poller/notifier, tray, IPC handlers
- `app/preload.ts` — the only bridge the renderer has into Node/Electron (contextIsolation on)
- `app/renderer/` — the UI itself: `index.html`, `style.css`, `renderer.ts`

## Notes
- Add a repository from the window; there's no branch picker or per-branch settings — every
  workflow run you triggered or committed, on any branch, shows up automatically.
- Tray colors follow priority: yellow (running) > red (failed) > green (succeeded) > gray (no runs yet).
- Config lives at `~/.config/gha-notifier/config.json` (Electron's per-user app data directory).
