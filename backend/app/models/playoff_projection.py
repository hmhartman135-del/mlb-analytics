"""
PlayoffProjection — cached AI playoff-race outlook (who's a lock, who's
vulnerable, who's the best bubble threat), grounded in real current
standings. One row per season; regenerated on request.
"""

from datetime import datetime
from sqlalchemy import Integer, String, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
import uuid
from ..core.database import Base


class PlayoffProjection(Base):
    __tablename__ = "playoff_projections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    season: Mapped[int] = mapped_column(Integer, index=True, unique=True)
    summary: Mapped[str] = mapped_column(String(3000))
    generated_at: Mapped[DateTime] = mapped_column(DateTime, default=datetime.utcnow)
