"""
PowerRanking — cached AI-generated power rankings (all 30 teams, ranked and
justified). One row per season; regenerated on request, not auto-refreshed.
"""

from datetime import datetime
from sqlalchemy import Integer, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
import uuid
from ..core.database import Base


class PowerRanking(Base):
    __tablename__ = "power_rankings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    season: Mapped[int] = mapped_column(Integer, index=True, unique=True)
    rankings: Mapped[list] = mapped_column(JSON)  # [{rank, team_name, team_abbr, division, record, blurb}, ...]
    generated_at: Mapped[DateTime] = mapped_column(DateTime, default=datetime.utcnow)
