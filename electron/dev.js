/**
 * dev.js — Start the app in development mode.
 *
 * Runs:
 *   1. FastAPI backend  (python -m uvicorn …)
 *   2. Next.js dev server  (next dev)
 *   3. Electron  (electron .)
 *
 * Usage from the electron/ directory:
 *   node dev.js
 */

const { spawn } = require("child_process");
const path = require("path");
const http = require("http");

const ROOT     = path.join(__dirname, "..");
const BACKEND  = path.join(ROOT, "backend");
const FRONTEND = path.join(ROOT, "frontend");

const processes = [];

function run(cmd, args, cwd, label, env = {}) {
  const proc = spawn(cmd, args, {
    cwd,
    env: { ...process.env, ...env },
    stdio: "pipe",
    shell: process.platform === "win32",
  });
  proc.stdout.on("data", d => process.stdout.write(`[${label}] ${d}`));
  proc.stderr.on("data", d => process.stderr.write(`[${label}] ${d}`));
  processes.push(proc);
  return proc;
}

function waitFor(url, label, timeoutMs = 60_000) {
  return new Promise((resolve, reject) => {
    const started = Date.now();
    const check = () => {
      http.get(url, (res) => {
        if (res.statusCode < 500) { console.log(`[dev] ${label} ready`); resolve(); }
        else retry();
      }).on("error", retry);
    };
    const retry = () => {
      if (Date.now() - started > timeoutMs) reject(new Error(`${label} never started`));
      else setTimeout(check, 1000);
    };
    setTimeout(check, 2000); // give processes a moment before first check
  });
}

function killAll() {
  processes.forEach(p => p.kill());
  process.exit(0);
}

process.on("SIGINT",  killAll);
process.on("SIGTERM", killAll);

(async () => {
  console.log("[dev] Starting backend…");
  const python = process.platform === "win32"
    ? path.join(BACKEND, ".venv", "Scripts", "python.exe")
    : path.join(BACKEND, ".venv", "bin", "python3");

  run(python, ["-m", "uvicorn", "app.main:app", "--reload", "--port", "8000"], BACKEND, "backend", {
    PYTHONUNBUFFERED: "1",
  });

  console.log("[dev] Starting Next.js…");
  run("npx", ["next", "dev", "--port", "3000"], FRONTEND, "frontend", {
    NEXT_PUBLIC_API_URL: "http://localhost:8000",
  });

  console.log("[dev] Waiting for servers…");
  try {
    await Promise.all([
      waitFor("http://localhost:8000/health", "backend"),
      waitFor("http://localhost:3000", "frontend"),
    ]);
  } catch (err) {
    console.error("[dev] Startup failed:", err.message);
    killAll();
  }

  console.log("[dev] Starting Electron…");
  const electron = require("electron");
  const elProc = run(electron, ["."], __dirname, "electron", {
    ELECTRON_IS_DEV: "1",
  });
  elProc.on("exit", killAll);
})();
