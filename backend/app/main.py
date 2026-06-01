import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from .core.database import engine, Base
from .api.routes import players, lineups, roster, scouting, analytics, teams, free_agency, standings, offseason, draft, trades, sync
from .models import spotrac_fa  # noqa — ensures table is registered with Base metadata


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Add any new columns that create_all won't backfill on existing tables
        await conn.execute(
            __import__("sqlalchemy").text(
                "ALTER TABLE players ADD COLUMN IF NOT EXISTS roster_status VARCHAR(16)"
            )
        )
    # Auto-sync rosters + stats at startup if data is >12 h old
    await sync.maybe_auto_sync()
    yield


app = FastAPI(
    title="MLB Analytics Platform",
    description="AI-powered MLB roster management, lineup optimization, and scouting",
    version="0.1.0",
    lifespan=lifespan,
)

# ALLOWED_ORIGINS env var — comma-separated list of allowed frontend URLs.
# In production set this to your Vercel URL e.g. https://mlb-analytics.vercel.app
# Multiple origins: "https://mlb-analytics.vercel.app,http://localhost:3000"
_raw_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000")
_allowed_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_origin_regex=r"https://.*\.vercel\.app",  # allow all Vercel preview URLs
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
    return {"status": "ok", "service": "MLB Analytics Platform"}
