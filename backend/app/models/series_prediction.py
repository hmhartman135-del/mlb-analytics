"""
SeriesPrediction — cached AI winner prediction for a real postseason series
that hasn't started yet, grounded in real regular-season records. One row
per series (keyed by season + round + team pair); regenerated on request.
"""

from datetime import datetime
from sqlalchemy import Integer, String, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
import uuid
from ..core.database import Base


class SeriesPrediction(Base):
    __tablename__ = "series_predictions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    series_key: Mapped[str] = mapped_column(String(100), index=True, unique=True)
    season: Mapped[int] = mapped_column(Integer, index=True)
    predicted_winner: Mapped[str] = mapped_column(String(200))
    confidence: Mapped[str] = mapped_column(String(50))
    reasoning: Mapped[str] = mapped_column(String(1000))
    generated_at: Mapped[DateTime] = mapped_column(DateTime, default=datetime.utcnow)
