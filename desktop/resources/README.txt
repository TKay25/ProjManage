This folder is copied into the packaged app as resources/resources/.

Put a PyInstaller build of the Flask server here so the installer does not
depend on Python being installed:

  server/yavaka-server.exe      (Windows)
  server/yavaka-server          (macOS / Linux)

Build it from the repository root, including the templates and static assets:

  pyinstaller --noconfirm --onefile --name yavaka-server ^
    --add-data "templates;templates" --add-data "static;static" ^
    app.py

Then copy dist/yavaka-server.exe into this folder and run `npm run dist` again.

The executable must serve HTTP on the PORT the desktop shell passes in the
environment; app.py already does that. The shell also sets DATABASE_FILE,
UPLOAD_DIR and SECRET_KEY, so nothing is written beside the installed app.

Without this executable the desktop shell falls back to a local Python
interpreter, which is fine for development but not for handing the installer to
somebody else.
