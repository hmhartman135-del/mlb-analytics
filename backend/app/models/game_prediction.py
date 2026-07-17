"""
GamePrediction — cached AI winner prediction for a scheduled game, grounded
in real records and probable pitchers. One row per game; regenerated on
request, not auto-refreshed.
"""

from datetime import datetime
from sqlalchemy import Integer, String, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
import uuid
from ..core.database import Base


class GamePrediction(Base):
    __tablename__ = "game_predictions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    game_pk: Mapped[int] = mapped_column(Integer, index=True, unique=True)
    predicted_winner: Mapped[str] = mapped_column(String(200))
    confidence: Mapped[str] = mapped_column(String(50))
    reasoning: Mapped[str] = mapped_column(String(1000))
    generated_at: Mapped[DateTime] = mapped_column(DateTime, default=datetime.utcnow)
