from sqlalchemy import String, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
import uuid
from ..core.database import Base


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sportradar_id: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    mlb_id: Mapped[int | None] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    abbreviation: Mapped[str] = mapped_column(String(8))
    city: Mapped[str] = mapped_column(String(64))
    division: Mapped[str | None] = mapped_column(String(32))   # AL East, NL West, etc.
    league: Mapped[str | None] = mapped_column(String(4))       # AL / NL
    ballpark: Mapped[str | None] = mapped_column(String(128))
    park_factor_runs: Mapped[float | None] = mapped_column()   # 100 = neutral
    park_factor_hr: Mapped[float | None] = mapped_column()

    # Minor league fields
    level: Mapped[str] = mapped_column(String(8), default="MLB")   # MLB, AAA, AA, A+, A, Rookie
    sport_id: Mapped[int | None] = mapped_column(Integer)           # MLB Stats API sport ID
    affiliate_mlb_id: Mapped[int | None] = mapped_column(Integer)   # parent MLB team's mlb_id

    players: Mapped[list["Player"]] = relationship("Player", back_populates="team", foreign_keys="Player.team_id")
