"""
SpotracFA — stores free-agent data scraped from spotrac.com/mlb/free-agents.

season=2026  →  current offseason free agents (2025-26 FA class)
season=2027  →  upcoming free agents (will be FAs after the 2026 season)
"""

from datetime import datetime
from sqlalchemy import String, Integer, Float, Boolean, DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
import uuid
from ..core.database import Base


class SpotracFA(Base):
    __tablename__ = "spotrac_fas"
    __table_args__ = (UniqueConstraint("season", "full_name"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # ── Classification ────────────────────────────────────────────────────────
    season: Mapped[int] = mapped_column(Integer, index=True)   # 2026 or 2027
    fa_type: Mapped[str | None] = mapped_column(String(16))    # "UFA", "ARFA", etc.

    # ── Player info ───────────────────────────────────────────────────────────
    full_name: Mapped[str] = mapped_column(String(128), index=True)
    position: Mapped[str | None] = mapped_column(String(32))
    age: Mapped[float | None] = mapped_column(Float)
    former_team: Mapped[str | None] = mapped_column(String(64))

    # ── Contract ──────────────────────────────────────────────────────────────
    signed: Mapped[bool] = mapped_column(Boolean, default=False)
    contract_years: Mapped[int | None] = mapped_column(Integer)
    contract_value: Mapped[int | None] = mapped_column(Integer)   # total $
    aav: Mapped[int | None] = mapped_column(Integer)              # annual avg $

    # ── Meta ──────────────────────────────────────────────────────────────────
    scraped_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
