/* YaVaKa desktop shell.

   Starts the Flask app on a free loopback port, waits for /health, then loads
   it in a native window. The renderer has no Node access: everything the UI can
   do is what the web app already allows. */

const { app, BrowserWindow, Menu, dialog, shell } = require("electron");
const { spawn } = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const http = require("node:http");
const net = require("node:net");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "..");
const isWindows = process.platform === "win32";

let serverProcess = null;
let mainWindow = null;
let baseUrl = "";
let updater = null;
let quitting = false;

/* ---------- Server ---------- */

function findPython() {
  const candidates = [
    process.env.YAVAKA_PYTHON,
    path.join(ROOT, ".venv", "Scripts", "python.exe"),
    path.join(ROOT, ".venv", "bin", "python"),
  ].filter(Boolean);

  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) return candidate;
  }
  return isWindows ? "python" : "python3";
}

function serverCommand() {
  if (process.env.YAVAKA_SERVER) {
    return { command: process.env.YAVAKA_SERVER, args: [] };
  }

  // A packaged build must ship its own server: there is no repository beside
  // an installed app, so `python app.py` has nothing to run.
  if (app.isPackaged) {
    const bundled = path.join(
      process.resourcesPath,
      "resources",
      "server",
      isWindows ? "yavaka-server.exe" : "yavaka-server",
    );
    if (fs.existsSync(bundled)) return { command: bundled, args: [] };
    throw new Error(
      "The bundled YaVaKa server is missing.\n\n" +
        "Build one with PyInstaller and place it in desktop/resources/server/ " +
        "before running npm run dist. See desktop/README.md.",
    );
  }

  return { command: findPython(), args: ["app.py"] };
}

function freePort() {
  return new Promise((resolve, reject) => {
    const probe = net.createServer();
    probe.unref();
    probe.on("error", reject);
    probe.listen(0, "127.0.0.1", () => {
      const { port } = probe.address();
      probe.close(() => resolve(port));
    });
  });
}

function waitForServer(url, timeoutMs = 45000) {
  const started = Date.now();
  return new Promise((resolve, reject) => {
    const retry = () => {
      if (Date.now() - started > timeoutMs) {
        reject(new Error("The local YaVaKa server did not come up in time."));
        return;
      }
      setTimeout(probe, 400);
    };

    const probe = () => {
      const request = http.get(url, (response) => {
        response.resume();
        if (response.statusCode === 200) resolve();
        else retry();
      });
      request.on("error", retry);
      request.setTimeout(2000, () => request.destroy());
    };

    probe();
  });
}

function desktopSecret() {
  const file = path.join(app.getPath("userData"), "secret.key");
  if (fs.existsSync(file)) return fs.readFileSync(file, "utf8").trim();
  const key = crypto.randomBytes(48).toString("base64url");
  fs.writeFileSync(file, key, { mode: 0o600 });
  return key;
}

async function startServer(port) {
  const { command, args } = serverCommand();
  const env = {
    ...process.env,
    PORT: String(port),
    HOST: "127.0.0.1",
    FLASK_DEBUG: "0",
    TRUST_PROXY: "0",
  };

  if (app.isPackaged) {
    // An installed app cannot write beside its own resources, so keep the
    // database, uploads and signing key in the per-user data folder.
    const dataDir = path.join(app.getPath("userData"), "data");
    fs.mkdirSync(path.join(dataDir, "uploads"), { recursive: true });
    env.DATABASE_FILE = path.join(dataDir, "vaka.db");
    env.UPLOAD_DIR = path.join(dataDir, "uploads");
    env.SECRET_KEY = desktopSecret();
  }

  serverProcess = spawn(command, args, {
    cwd: app.isPackaged ? app.getPath("userData") : ROOT,
    env,
    stdio: ["ignore", "pipe", "pipe"],
    windowsHide: true,
  });

  const prefix = (line) => `[yavaka] ${line}`;
  serverProcess.stdout.on("data", (chunk) => process.stdout.write(prefix(chunk)));
  serverProcess.stderr.on("data", (chunk) => process.stderr.write(prefix(chunk)));
  serverProcess.on("exit", (code) => {
    serverProcess = null;
    if (!quitting) {
      dialog.showErrorBox(
        "YaVaKa stopped",
        `The local server exited with code ${code}. Restart the app to try again.`,
      );
    }
  });
  serverProcess.on("error", (error) => {
    dialog.showErrorBox(
      "YaVaKa could not start",
      `${error.message}\n\nSet YAVAKA_PYTHON to your Python executable, or install Python 3.10+.`,
    );
  });

  await waitForServer(`http://127.0.0.1:${port}/health`);
}

function stopServer() {
  if (!serverProcess) return;
  const child = serverProcess;
  serverProcess = null;
  try {
    if (isWindows) {
      // app.py spawns no children, but taskkill takes the tree if it ever does.
      spawn("taskkill", ["/pid", String(child.pid), "/t", "/f"], { windowsHide: true });
    } else {
      child.kill("SIGTERM");
    }
  } catch (error) {
    /* already gone */
  }
}

/* ---------- Window ---------- */

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1320,
    height: 900,
    minWidth: 920,
    minHeight: 620,
    backgroundColor: "#F7F4EF",
    title: "YaVaKa",
    autoHideMenuBar: false,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      spellcheck: true,
    },
  });

  mainWindow.loadURL(`${baseUrl}/app`);

  // Anything outside the local server belongs in the real browser.
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith(baseUrl)) return { action: "allow" };
    shell.openExternal(url);
    return { action: "deny" };
  });

  mainWindow.webContents.on("will-navigate", (event, url) => {
    if (url.startsWith(baseUrl)) return;
    event.preventDefault();
    shell.openExternal(url);
  });

  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

/* ---------- Updates ---------- */

function initUpdater() {
  const feed = process.env.YAVAKA_UPDATE_URL;
  if (!feed || !app.isPackaged) return null;

  try {
    const { autoUpdater } = require("electron-updater");
    autoUpdater.setFeedURL({ provider: "generic", url: feed });
    autoUpdater.autoDownload = true;
    autoUpdater.on("error", (error) => console.error("[yavaka] update check failed:", error.message));
    return autoUpdater;
  } catch (error) {
    console.warn("[yavaka] electron-updater is unavailable:", error.message);
    return null;
  }
}

function checkForUpdates(interactive) {
  if (!updater) {
    if (interactive) {
      dialog.showMessageBox({
        type: "info",
        title: "Updates",
        message: "Update checks are not configured.",
        detail:
          "Set YAVAKA_UPDATE_URL to the folder that hosts the published update files, then rebuild the installer.",
      });
    }
    return;
  }

  updater.checkForUpdates().catch((error) => {
    if (interactive) {
      dialog.showMessageBox({ type: "error", title: "Updates", message: error.message });
    }
  });
}

/* ---------- Menu ---------- */

function buildMenu() {
  const template = [
    {
      label: "YaVaKa",
      submenu: [
        { label: "Reload", accelerator: "CmdOrCtrl+R", click: () => mainWindow?.reload() },
        { type: "separator" },
        {
          label: "Open data folder",
          click: () => {
            const folder = app.isPackaged
              ? path.join(app.getPath("userData"), "data")
              : path.join(ROOT, "instance");
            shell.openPath(folder);
          },
        },
        {
          label: "Back up database",
          click: () => {
            if (mainWindow) mainWindow.webContents.downloadURL(`${baseUrl}/app/settings/backup`);
          },
        },
        { type: "separator" },
        { label: "Check for updates", click: () => checkForUpdates(true) },
        { type: "separator" },
        { role: "quit" },
      ],
    },
    { role: "editMenu" },
    { role: "viewMenu" },
    { role: "windowMenu" },
    {
      role: "help",
      submenu: [
        {
          label: "YaVaKa web app",
          click: () => shell.openExternal("https://yavaka.co.zw"),
        },
      ],
    },
  ];

  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

/* ---------- Lifecycle ---------- */

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });

  app.whenReady().then(async () => {
    try {
      const port = await freePort();
      baseUrl = `http://127.0.0.1:${port}`;
      await startServer(port);
    } catch (error) {
      dialog.showErrorBox("YaVaKa could not start", error.message);
      app.quit();
      return;
    }

    updater = initUpdater();
    createWindow();
    buildMenu();
    checkForUpdates(false);
  });

  app.on("window-all-closed", () => app.quit());

  app.on("before-quit", () => {
    quitting = true;
    stopServer();
  });
}
