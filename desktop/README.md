# YaVaKa desktop

An Electron shell around the same Flask app. It starts the server on a free
loopback port, waits for `/health`, then opens it in a native window. Nothing
about the web app changes — the renderer has no Node access.

## Develop

```powershell
cd desktop
npm install
npm start
```

The shell prefers, in order: `YAVAKA_PYTHON`, `.venv\Scripts\python.exe` in the
repository, `python` on `PATH`. In development it reuses the repository's
`instance/vaka.db` and `uploads/`, so the desktop window and the browser see the
same data.

## Build an installer

```powershell
cd desktop
npm run dist
```

Output lands in `desktop/dist/`: an NSIS installer and a portable `.exe`.

A packaged build must not depend on the machine having Python. Build a single
executable server first and drop it in `desktop/resources/server/`:

```powershell
python -m pip install pyinstaller
pyinstaller --noconfirm --onefile --name yavaka-server `
  --add-data "templates;templates" --add-data "static;static" app.py
```

Then `npm run dist` bundles it. Without it, the packaged app stops at startup
with a clear message instead of failing halfway through. A packaged app keeps
its database, uploads and session key in `%APPDATA%\YaVaKa` (Electron's
`userData` folder), never beside the installed files.

| Environment variable | Effect |
| --- | --- |
| `YAVAKA_PYTHON` | Interpreter used in development |
| `YAVAKA_SERVER` | Full path to the server executable, overrides everything |
| `YAVAKA_UPDATE_URL` | Folder that hosts `latest.yml` and the installers; enables update checks |

## Updates

`electron-updater` is wired to a **generic** feed: publish `latest.yml`, the
installer and the blockmap to the URL in `YAVAKA_UPDATE_URL`. Until that is set,
"Check for updates" explains that update checks are not configured. Signing
certificates and the publish target are deployment decisions, not something this
repository can supply.

## Backups

The **YaVaKa → Back up database** menu item downloads `/app/settings/backup`,
which zips a consistent SQLite snapshot plus the uploads folder. It is
restricted to staff accounts, and the same button is on the Settings page in the
browser.
