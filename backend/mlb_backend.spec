# mlb_backend.spec
# PyInstaller spec — builds the FastAPI backend into a single executable.
#
# Build with (from backend/ directory):
#   .venv/bin/pyinstaller mlb_backend.spec --clean
#
# Output:  backend/dist/mlb-backend   (Mac/Linux)
#          backend/dist/mlb-backend.exe  (Windows)

import sys
import os
from pathlib import Path

block_cipher = None
ROOT = Path(SPECPATH)  # noqa: F821  (SPECPATH injected by PyInstaller)

# ── Collect all app source files ──────────────────────────────────────────────
datas = [
    # Include the entire app package
    (str(ROOT / "app"), "app"),
    # Alembic migrations (if you use them)
    # (str(ROOT / "alembic"), "alembic"),
]

# Include the bundled .env (created by build-app.sh with real credentials)
bundled_env = ROOT / ".env.bundled"
if bundled_env.exists():
    datas.append((str(bundled_env), ".env"))
else:
    # Fallback: include the dev .env (won't have prod creds, but won't crash build)
    dev_env = ROOT / ".env"
    if dev_env.exists():
        datas.append((str(dev_env), ".env"))

# ── Hidden imports PyInstaller misses via static analysis ─────────────────────
hidden = [
    # uvicorn internals
    "uvicorn.logging",
    "uvicorn.loops", "uvicorn.loops.auto", "uvicorn.loops.asyncio",
    "uvicorn.protocols", "uvicorn.protocols.http", "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl", "uvicorn.protocols.http.httptools_impl",
    "uvicorn.protocols.websockets", "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.protocols.websockets.wsproto_impl",
    "uvicorn.lifespan", "uvicorn.lifespan.on", "uvicorn.lifespan.off",
    # asyncpg / SQLAlchemy
    "asyncpg", "asyncpg.pgproto", "asyncpg.pgproto.pgproto",
    "sqlalchemy.dialects.postgresql",
    "sqlalchemy.dialects.postgresql.asyncpg",
    "sqlalchemy.dialects.postgresql.base",
    "sqlalchemy.ext.asyncio",
    # pydantic
    "pydantic", "pydantic_settings", "pydantic.v1",
    # httpx / h11 / anyio
    "httpx", "h11", "anyio", "anyio._backends._asyncio", "sniffio",
    # dotenv
    "dotenv",
    # anthropic
    "anthropic",
    # misc
    "multipart", "email_validator",
    "passlib", "passlib.handlers.bcrypt",
    "jose", "jose.backends",
    "aiofiles",
    "starlette.middleware.cors",
]

a = Analysis(
    [str(ROOT / "server.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "pandas", "PIL", "cv2", "torch"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="mlb-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,   # keep console so Electron can read stdout/stderr
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
