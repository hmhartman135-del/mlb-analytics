from sqlalchemy import String, Integer, Float, Boolean, Date, Enum, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
import uuid
import enum
from ..core.database import Base


class PlayerStatus(str, enum.Enum):
    active = "active"
    injured = "injured"
    minors = "minors"
    free_agent = "free_agent"
    retired = "retired"
    draft_prospect = "draft_prospect"


class Position(str, enum.Enum):
    SP = "SP"   # Starting Pitcher
    RP = "RP"   # Relief Pitcher
    C = "C"
    FIRST = "1B"
    SECOND = "2B"
    THIRD = "3B"
    SS = "SS"
    LF = "LF"
    CF = "CF"
    RF = "RF"
    DH = "DH"


class Handedness(str, enum.Enum):
    L = "L"
    R = "R"
    S = "S"  # Switch


class Player(Base):
    __tablename__ = "players"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sportradar_id: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    mlb_id: Mapped[int | None] = mapped_column(Integer, unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(128), nullable=False)
    first_name: Mapped[str] = mapped_column(String(64))
    last_name: Mapped[str] = mapped_column(String(64))
    birth_date: Mapped[Date | None] = mapped_column(Date)
    age: Mapped[int | None] = mapped_column(Integer)

    position: Mapped[str | None] = mapped_column(String(8))
    secondary_positions: Mapped[list | None] = mapped_column(JSON)
    bats: Mapped[str | None] = mapped_column(String(2))   # L/R/S
    throws: Mapped[str | None] = mapped_column(String(2))  # L/R

    status: Mapped[str] = mapped_column(String(32), default="active")
    # 40-man/26-man roster status code from MLB Stats API:
    # "A"=26-man active  "D10/D15/D60"=IL  "RM"=reassigned to minors  None=not on 40-man
    roster_status: Mapped[str | None] = mapped_column(String(16))
    minor_league_level: Mapped[str | None] = mapped_column(String(8))  # AAA, AA, A+, A, Rookie
    team_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("teams.id"))
    jersey_number: Mapped[int | None] = mapped_column(Integer)
    salary: Mapped[float | None] = mapped_column(Float)  # in millions
    contract_years: Mapped[int | None] = mapped_column(Integer)
    service_time: Mapped[float | None] = mapped_column(Float)  # years

    # Bio / physical
    height: Mapped[str | None] = mapped_column(String(15))        # "6' 2\""
    weight: Mapped[int | None] = mapped_column(Integer)           # lbs
    birth_city: Mapped[str | None] = mapped_column(String(100))
    birth_country: Mapped[str | None] = mapped_column(String(100))
    school: Mapped[str | None] = mapped_column(String(200))       # college / HS
    draft_year: Mapped[int | None] = mapped_column(Integer)
    draft_pick: Mapped[int | None] = mapped_column(Integer)       # overall pick number
    draft_rank: Mapped[int | None] = mapped_column(Integer)       # MLB Pipeline pre-draft rank
    signing_bonus: Mapped[float | None] = mapped_column(Float)    # in dollars
    school_class: Mapped[str | None] = mapped_column(String(20))  # "4YR JR", "HS SR", etc.
    prospect_rank: Mapped[int | None] = mapped_column(Integer)    # overall top-100 rank
    org_prospect_rank: Mapped[int | None] = mapped_column(Integer)  # top-30 within org
    parent_org_mlb_id: Mapped[int | None] = mapped_column(Integer)  # MLB parent team mlb_id
    parent_org_abbr: Mapped[str | None] = mapped_column(String(8))  # e.g. "NYY", "LAD"

    # Scouting grades (20-80 scale)
    scout_hit: Mapped[int | None] = mapped_column(Integer)
    scout_power: Mapped[int | None] = mapped_column(Integer)
    scout_speed: Mapped[int | None] = mapped_column(Integer)
    scout_field: Mapped[int | None] = mapped_column(Integer)
    scout_arm: Mapped[int | None] = mapped_column(Integer)
    scout_fb_velo: Mapped[int | None] = mapped_column(Integer)   # pitchers
    scout_command: Mapped[int | None] = mapped_column(Integer)    # pitchers
    scout_overall: Mapped[int | None] = mapped_column(Integer)
    scout_notes: Mapped[str | None] = mapped_column(String(2048))

    team: Mapped["Team"] = relationship("Team", back_populates="players")
    batting_stats: Mapped[list["BattingStats"]] = relationship("BattingStats", back_populates="player")
    pitching_stats: Mapped[list["PitchingStats"]] = relationship("PitchingStats", back_populates="player")
