import os
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from .core.database import engine, Base
from .api.routes import players, lineups, roster, scouting, analytics, teams, free_agency, standings, offseason, draft, trades, sync
from .models import spotrac_fa  # noqa — ensures table is registered with Base metadata

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # DB setup runs in a background task so it NEVER blocks startup.
    # Railway health check passes immediately; tables are ready within seconds.
    import asyncio

    async def _setup_db():
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                await conn.execute(
                    __import__("sqlalchemy").text(
                        "ALTER TABLE players ADD COLUMN IF NOT EXISTS roster_status VARCHAR(16)"
                    )
                )
            logger.info("DB tables ready")
        except Exception as exc:
            logger.warning("DB setup error (non-fatal): %s", exc)

    asyncio.create_task(_setup_db())
    yield


app = FastAPI(
    title="MLB Analytics Platform",
    description="AI-powered MLB roster management, lineup optimization, and scouting",
    version="0.1.0",
    lifespan=lifespan,
)

_raw_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000")
_allowed_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(teams.router, prefix="/api/v1")
app.include_router(players.router, prefix="/api/v1")
app.include_router(lineups.router, prefix="/api/v1")
app.include_router(roster.router, prefix="/api/v1")
app.include_router(scouting.router, prefix="/api/v1")
app.include_router(analytics.router, prefix="/api/v1")
app.include_router(free_agency.router)
app.include_router(standings.router)
app.include_router(offseason.router, prefix="/api/v1")
app.include_router(draft.router, prefix="/api/v1")
app.include_router(trades.router, prefix="/api/v1")
app.include_router(sync.router)


@app.get("/health")
async def health():
    """Intentionally does NOT touch the database — always responds immediately."""
    return {"status": "ok", "service": "MLB Analytics Platform"}


@app.get("/healthz")
async def healthz():
    """Kubernetes-style alias — also DB-free."""
    return {"status": "ok"}


@app.get("/")
async def root():
    return {
        "service": "MLB Analytics Platform API",
        "status": "running",
        "docs": "/docs",
        "health": "/health",
        "note": "Open the Vercel frontend URL to use the app — this is the API backend only."
    }
