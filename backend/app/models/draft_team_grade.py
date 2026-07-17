"""
DraftTeamGrade — cached AI-written grade for a team's real completed draft
class (e.g. the 2026 draft). One row per (team, draft_year); regenerated
on request via POST /draft-results/{year}/team/{team_id}/grade.
"""

from datetime import datetime
from sqlalchemy import String, Integer, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
import uuid
from ..core.database import Base


class DraftTeamGrade(Base):
    __tablename__ = "draft_team_grades"
    __table_args__ = (UniqueConstraint("team_id", "draft_year"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("teams.id"), index=True)
    draft_year: Mapped[int] = mapped_column(Integer, index=True)
    grade: Mapped[str] = mapped_column(String(4))       # "A+", "B-", etc.
    analysis: Mapped[str] = mapped_column(String(4000))
    generated_at: Mapped[DateTime] = mapped_column(DateTime, default=datetime.utcnow)
