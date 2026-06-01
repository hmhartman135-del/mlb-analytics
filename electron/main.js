/**
 * Electron main process — MLB Analytics Desktop App
 *
 * Startup sequence:
 *   1. Check if first run (no Anthropic key stored yet) → show setup screen
 *   2. Show splash screen
 *   3. Start the FastAPI backend  (bundled mlb-backend binary in prod, venv python in dev)
 *   4. Start the Next.js server   (standalone build in prod, next dev in dev)
 *   5. Poll until both respond, then open main window
 *   6. On close → kill child processes cleanly
 */

const {
  app, BrowserWindow, shell, ipcMain,
  safeStorage, dialog,
} = require("electron");
const path    = require("path");
const { spawn } = require("child_process");
const http    = require("http");
const fs      = require("fs");
const os      = require("os");
const log     = require("electron-log");

// ── Environment ───────────────────────────────────────────────────────────────
const isDev = !app.isPackaged;

// ── Paths ─────────────────────────────────────────────────────────────────────
const RESOURCES = isDev
  ? path.join(__dirname, "..")          // repo root in dev
  : process.resourcesPath;             // inside .app/.exe in prod

const BACKEND_DIR  = path.join(RESOURCES, "backend");
const FRONTEND_DIR = path.join(RESOURCES, "frontend");

// PyInstaller binary lives in resources/mlb-backend (prod) or is the venv python (dev)
const BACKEND_BINARY = isDev
  ? null   // we'll use venv python in dev
  : path.join(process.resourcesPath, process.platform === "win32" ? "mlb-backend.exe" : "mlb-backend");

const BACKEND_PORT  = 8000;
const FRONTEND_PORT = 3000;

// Secure key storage file path (fallback for platforms where safeStorage isn't supported)
const KEY_FILE = path.join(app.getPath("userData"), "anthropic_key.enc");

// ── Logging ───────────────────────────────────────────────────────────────────
log.initialize({ preload: true });
log.transports.file.level = isDev ? "debug" : "warn";
log.info("Starting MLB Analytics —", isDev ? "DEV" : "PROD");

// ── Child processes ───────────────────────────────────────────────────────────
let backendProc  = null;
let frontendProc = null;
let mainWindow   = null;
let splashWindow = null;
let setupWindow  = null;

// ─────────────────────────────────────────────────────────────────────────────
// API key — secure storage helpers
// ─────────────────────────────────────────────────────────────────────────────

function saveApiKey(key) {
  try {
    if (safeStorage.isEncryptionAvailable()) {
      const encrypted = safeStorage.encryptString(key);
      fs.writeFileSync(KEY_FILE, encrypted);
    } else {
      // Fallback: plain text (not ideal but functional on unsupported platforms)
      fs.writeFileSync(KEY_FILE, key, "utf8");
    }
    log.info("API key saved to", KEY_FILE);
  } catch (err) {
    log.error("Failed to save API key:", err);
  }
}

function loadApiKey() {
  try {
    if (!fs.existsSync(KEY_FILE)) return null;
    const data = fs.readFileSync(KEY_FILE);
    if (safeStorage.isEncryptionAvailable() && Buffer.isBuffer(data)) {
      return safeStorage.decryptString(data);
    }
    return data.toString("utf8").trim() || null;
  } catch (err) {
    log.warn("Could not load API key:", err.message);
    return null;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Server helpers
// ─────────────────────────────────────────────────────────────────────────────

function waitForServer(url, timeoutMs = 90_000) {
  return new Promise((resolve, reject) => {
    const started = Date.now();
    const check = () => {
      http.get(url, (res) => {
        if (res.statusCode < 500) { resolve(); return; }
        retry();
      }).on("error", retry);
    };
    const retry = () => {
      if (Date.now() - started > timeoutMs) {
        reject(new Error(`Timed out waiting for ${url}`));
        return;
      }
      setTimeout(check, 1000);
    };
    setTimeout(check, 1500);
  });
}

function findVenvPython() {
  const candidates = [
    path.join(BACKEND_DIR, ".venv", "bin", "python3"),
    path.join(BACKEND_DIR, ".venv", "Scripts", "python.exe"),
  ];
  for (const p of candidates) {
    try { if (fs.existsSync(p)) return p; } catch {}
  }
  return "python3";
}

function loadDotEnv(envPath) {
  const env = {};
  if (!fs.existsSync(envPath)) return env;
  fs.readFileSync(envPath, "utf8")
    .split("\n")
    .forEach(line => {
      line = line.trim();
      if (!line || line.startsWith("#")) return;
      const idx = line.indexOf("=");
      if (idx < 0) return;
      const k = line.slice(0, idx).trim();
      const v = line.slice(idx + 1).trim().replace(/^["']|["']$/g, "");
      if (k) env[k] = v;
    });
  return env;
}

// ─────────────────────────────────────────────────────────────────────────────
// Start backend
// ─────────────────────────────────────────────────────────────────────────────

function startBackend(anthropicKey) {
  const envOverrides = {
    ...loadDotEnv(path.join(BACKEND_DIR, ".env")),
    PYTHONUNBUFFERED: "1",
    BACKEND_PORT: String(BACKEND_PORT),
  };
  if (anthropicKey) envOverrides.ANTHROPIC_API_KEY = anthropicKey;

  const env = { ...process.env, ...envOverrides };

  if (isDev) {
    // Development: use venv python
    const python = findVenvPython();
    log.info("[backend] DEV mode — python:", python);
    backendProc = spawn(
      python,
      ["-m", "uvicorn", "app.main:app", "--reload", "--host", "127.0.0.1", "--port", String(BACKEND_PORT)],
      { cwd: BACKEND_DIR, env, windowsHide: true }
    );
  } else {
    // Production: use bundled PyInstaller binary
    log.info("[backend] PROD mode — binary:", BACKEND_BINARY);
    if (!fs.existsSync(BACKEND_BINARY)) {
      dialog.showErrorBox("Missing backend", `Backend binary not found:\n${BACKEND_BINARY}\n\nPlease reinstall the app.`);
      app.quit();
      return;
    }
    backendProc = spawn(BACKEND_BINARY, [], { env, windowsHide: true });
  }

  backendProc.stdout.on("data", d => log.info("[backend]", d.toString().trim()));
  backendProc.stderr.on("data", d => log.warn("[backend]", d.toString().trim()));
  backendProc.on("exit", code => {
    log.warn("[backend] exited with code", code);
    if (code !== 0 && mainWindow) {
      mainWindow.webContents.executeJavaScript(
        `console.error('[desktop] Backend process exited unexpectedly (code ${code})')`
      );
    }
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// Start Next.js
// ─────────────────────────────────────────────────────────────────────────────

function startFrontend() {
  const frontendEnv = {
    ...process.env,
    NODE_ENV: "production",
    NEXT_PUBLIC_API_URL: `http://127.0.0.1:${BACKEND_PORT}`,
    PORT: String(FRONTEND_PORT),
    HOSTNAME: "127.0.0.1",
  };

  if (isDev) {
    // Development: next dev
    const npmCmd = process.platform === "win32" ? "npm.cmd" : "npx";
    frontendProc = spawn(
      npmCmd,
      ["next", "dev", "--port", String(FRONTEND_PORT)],
      { cwd: FRONTEND_DIR, env: frontendEnv, windowsHide: true }
    );
  } else {
    // Production: start the Next.js standalone server
    // next build --output standalone creates .next/standalone/server.js
    const standaloneServer = path.join(FRONTEND_DIR, ".next", "standalone", "server.js");
    const node = process.execPath;  // Electron's bundled Node.js
    log.info("[frontend] standalone server:", standaloneServer);

    if (!fs.existsSync(standaloneServer)) {
      dialog.showErrorBox(
        "Missing frontend build",
        `Frontend not built.\nExpected: ${standaloneServer}\n\nPlease reinstall the app.`
      );
      app.quit();
      return;
    }
    frontendProc = spawn(node, [standaloneServer], {
      cwd: path.join(FRONTEND_DIR, ".next", "standalone"),
      env: frontendEnv,
      windowsHide: true,
    });
  }

  frontendProc.stdout.on("data", d => log.info("[frontend]", d.toString().trim()));
  frontendProc.stderr.on("data", d => log.warn("[frontend]", d.toString().trim()));
  frontendProc.on("exit", code => log.warn("[frontend] exited with code", code));
}

// ─────────────────────────────────────────────────────────────────────────────
// Windows
// ─────────────────────────────────────────────────────────────────────────────

function createSplash() {
  splashWindow = new BrowserWindow({
    width: 480, height: 300,
    frame: false, transparent: true,
    resizable: false, alwaysOnTop: true,
    webPreferences: { nodeIntegration: false, contextIsolation: true },
  });
  splashWindow.loadFile(path.join(__dirname, "splash.html"));
  splashWindow.center();
}

function createSetupWindow() {
  setupWindow = new BrowserWindow({
    width: 560, height: 460,
    resizable: false,
    titleBarStyle: "hiddenInset",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  setupWindow.loadFile(path.join(__dirname, "setup.html"));
  setupWindow.center();
}

function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1440, height: 900,
    minWidth: 1024, minHeight: 700,
    show: false,
    titleBarStyle: process.platform === "darwin" ? "hiddenInset" : "default",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.loadURL(`http://127.0.0.1:${FRONTEND_PORT}`);
  mainWindow.once("ready-to-show", () => {
    if (splashWindow && !splashWindow.isDestroyed()) splashWindow.destroy();
    mainWindow.show();
    if (isDev) mainWindow.webContents.openDevTools();
  });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith("http")) shell.openExternal(url);
    return { action: "deny" };
  });

  mainWindow.on("closed", () => { mainWindow = null; });
}

// ─────────────────────────────────────────────────────────────────────────────
// Cleanup
// ─────────────────────────────────────────────────────────────────────────────

function killAll() {
  [backendProc, frontendProc].forEach(proc => {
    if (!proc) return;
    try {
      if (process.platform === "win32") {
        spawn("taskkill", ["/pid", String(proc.pid), "/f", "/t"]);
      } else {
        proc.kill("SIGTERM");
      }
    } catch {}
  });
  backendProc = frontendProc = null;
}

app.on("before-quit", killAll);
app.on("will-quit",   killAll);
process.on("SIGTERM", () => { killAll(); app.quit(); });
process.on("SIGINT",  () => { killAll(); app.quit(); });

// ─────────────────────────────────────────────────────────────────────────────
// IPC handlers
// ─────────────────────────────────────────────────────────────────────────────

// Setup screen sends the API key here
ipcMain.handle("save-api-key", async (_event, key) => {
  if (!key || !key.startsWith("sk-ant-")) {
    return { ok: false, error: "That doesn't look like a valid Anthropic API key (should start with sk-ant-)" };
  }
  saveApiKey(key);
  return { ok: true };
});

ipcMain.handle("get-api-key",  () => loadApiKey());
ipcMain.handle("app-version",  () => app.getVersion());
ipcMain.handle("is-dev",       () => isDev);
ipcMain.handle("open-logs",    () => shell.openPath(log.transports.file.getFile().path));

// Called by setup screen after key is saved — launches the real app
ipcMain.handle("setup-complete", async () => {
  if (setupWindow && !setupWindow.isDestroyed()) setupWindow.destroy();
  await launchApp();
});

// ─────────────────────────────────────────────────────────────────────────────
// Main launch sequence
// ─────────────────────────────────────────────────────────────────────────────

async function launchApp() {
  const apiKey = loadApiKey();

  createSplash();
  startBackend(apiKey);
  startFrontend();

  try {
    await Promise.all([
      waitForServer(`http://127.0.0.1:${BACKEND_PORT}/health`),
      waitForServer(`http://127.0.0.1:${FRONTEND_PORT}`),
    ]);
    log.info("Both servers ready");
    createMainWindow();
  } catch (err) {
    log.error("Startup failed:", err);
    if (splashWindow && !splashWindow.isDestroyed()) {
      splashWindow.webContents.executeJavaScript(
        `document.getElementById('status').textContent = 'Startup failed — check logs'`
      );
    }
    setTimeout(() => app.quit(), 4000);
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Entry point
// ─────────────────────────────────────────────────────────────────────────────

app.whenReady().then(async () => {
  const existingKey = loadApiKey();

  if (!existingKey) {
    // First run — show setup screen so user can enter their Anthropic key
    log.info("First run — showing setup screen");
    createSetupWindow();
  } else {
    // Key already stored — launch directly
    await launchApp();
  }
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) launchApp();
});
