from sqlalchemy import String, Integer, Float, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
import uuid
from ..core.database import Base


class BattingStats(Base):
    __tablename__ = "batting_stats"
    __table_args__ = (UniqueConstraint("player_id", "season", "split"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    player_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("players.id"), index=True)
    season: Mapped[int] = mapped_column(Integer)
    split: Mapped[str] = mapped_column(String(32), default="overall")  # overall, vs_LHP, vs_RHP, home, away

    # Counting stats
    games: Mapped[int] = mapped_column(Integer, default=0)
    plate_appearances: Mapped[int] = mapped_column(Integer, default=0)
    at_bats: Mapped[int] = mapped_column(Integer, default=0)
    hits: Mapped[int] = mapped_column(Integer, default=0)
    doubles: Mapped[int] = mapped_column(Integer, default=0)
    triples: Mapped[int] = mapped_column(Integer, default=0)
    home_runs: Mapped[int] = mapped_column(Integer, default=0)
    rbi: Mapped[int] = mapped_column(Integer, default=0)
    runs: Mapped[int] = mapped_column(Integer, default=0)
    walks: Mapped[int] = mapped_column(Integer, default=0)
    strikeouts: Mapped[int] = mapped_column(Integer, default=0)
    stolen_bases: Mapped[int] = mapped_column(Integer, default=0)
    caught_stealing: Mapped[int] = mapped_column(Integer, default=0)
    hit_by_pitch: Mapped[int] = mapped_column(Integer, default=0)
    sacrifice_flies: Mapped[int] = mapped_column(Integer, default=0)

    # Rate stats
    avg: Mapped[float | None] = mapped_column(Float)
    obp: Mapped[float | None] = mapped_column(Float)
    slg: Mapped[float | None] = mapped_column(Float)
    ops: Mapped[float | None] = mapped_column(Float)
    ops_plus: Mapped[float | None] = mapped_column(Float)

    # Advanced metrics
    woba: Mapped[float | None] = mapped_column(Float)        # Weighted on-base average
    wrc_plus: Mapped[float | None] = mapped_column(Float)    # Park/league adjusted wRC
    babip: Mapped[float | None] = mapped_column(Float)       # Batting avg on balls in play
    iso: Mapped[float | None] = mapped_column(Float)         # Isolated power (SLG - AVG)
    xba: Mapped[float | None] = mapped_column(Float)         # Expected batting average (Statcast)
    xslg: Mapped[float | None] = mapped_column(Float)
    xwoba: Mapped[float | None] = mapped_column(Float)
    hard_hit_pct: Mapped[float | None] = mapped_column(Float)
    barrel_pct: Mapped[float | None] = mapped_column(Float)
    sprint_speed: Mapped[float | None] = mapped_column(Float)  # ft/sec
    war: Mapped[float | None] = mapped_column(Float)

    player: Mapped["Player"] = relationship("Player", back_populates="batting_stats")


class PitchingStats(Base):
    __tablename__ = "pitching_stats"
    __table_args__ = (UniqueConstraint("player_id", "season", "split"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    player_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("players.id"), index=True)
    season: Mapped[int] = mapped_column(Integer)
    split: Mapped[str] = mapped_column(String(32), default="overall")

    # Counting stats
    games: Mapped[int] = mapped_column(Integer, default=0)
    games_started: Mapped[int] = mapped_column(Integer, default=0)
    wins: Mapped[int] = mapped_column(Integer, default=0)
    losses: Mapped[int] = mapped_column(Integer, default=0)
    saves: Mapped[int] = mapped_column(Integer, default=0)
    innings_pitched: Mapped[float] = mapped_column(Float, default=0)
    hits_allowed: Mapped[int] = mapped_column(Integer, default=0)
    runs_allowed: Mapped[int] = mapped_column(Integer, default=0)
    earned_runs: Mapped[int] = mapped_column(Integer, default=0)
    walks: Mapped[int] = mapped_column(Integer, default=0)
    strikeouts: Mapped[int] = mapped_column(Integer, default=0)
    home_runs_allowed: Mapped[int] = mapped_column(Integer, default=0)

    # Rate stats
    era: Mapped[float | None] = mapped_column(Float)
    whip: Mapped[float | None] = mapped_column(Float)
    k_per_9: Mapped[float | None] = mapped_column(Float)
    bb_per_9: Mapped[float | None] = mapped_column(Float)
    hr_per_9: Mapped[float | None] = mapped_column(Float)
    k_pct: Mapped[float | None] = mapped_column(Float)
    bb_pct: Mapped[float | None] = mapped_column(Float)
    era_plus: Mapped[float | None] = mapped_column(Float)

    # Advanced / Statcast
    fip: Mapped[float | None] = mapped_column(Float)         # Fielding Independent Pitching
    xfip: Mapped[float | None] = mapped_column(Float)        # Expected FIP
    siera: Mapped[float | None] = mapped_column(Float)       # Skill-Interactive ERA
    babip_against: Mapped[float | None] = mapped_column(Float)
    lob_pct: Mapped[float | None] = mapped_column(Float)     # Left on base %
    gb_pct: Mapped[float | None] = mapped_column(Float)      # Ground ball %
    fb_pct: Mapped[float | None] = mapped_column(Float)      # Fly ball %
    avg_fastball_velo: Mapped[float | None] = mapped_column(Float)
    avg_spin_rate: Mapped[float | None] = mapped_column(Float)
    xera: Mapped[float | None] = mapped_column(Float)        # Expected ERA (Statcast)
    war: Mapped[float | None] = mapped_column(Float)

    player: Mapped["Player"] = relationship("Player", back_populates="pitching_stats")
