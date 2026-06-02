#!/usr/bin/env python3
"""
server.py — Standalone entry point for PyInstaller.

This file becomes the single `mlb-backend` executable that ships inside
the Electron app.  It contains the entire FastAPI app + all Python deps.

Electron starts it like any subprocess, passing the user's API key and
the Supabase DATABASE_URL as environment variables.
"""
import sys
import os

# ── PyInstaller bundle path setup ─────────────────────────────────────────────
if getattr(sys, "frozen", False):
    # _MEIPASS = temp directory where PyInstaller extracted everything
    _bundle_dir = sys._MEIPASS  # noqa: SLF001
    sys.path.insert(0, _bundle_dir)
    os.chdir(_bundle_dir)

    # Load the bundled .env (DATABASE_URL, etc.)
    # Env vars already set by Electron take priority (override=False).
    _env_path = os.path.join(_bundle_dir, ".env")
    if os.path.exists(_env_path):
        from dotenv import load_dotenv
        load_dotenv(_env_path, override=False)

# Export app at module level so `uvicorn server:app` works (used by Railway)
from app.main import app  # noqa: E402

# ── Start uvicorn ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("BACKEND_PORT", 8000))
    print(f"[backend] Starting on http://127.0.0.1:{port}", flush=True)

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )
