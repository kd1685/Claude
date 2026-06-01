"""Pydantic request/response models."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

RANK_NAMES = {1: "R1", 2: "R2", 3: "R3", 4: "R4 (Officer)", 5: "R5 (Leader)"}
TITLES = ["Justice", "Duke", "Architect", "Scientist"]


class PlayerIn(BaseModel):
    name: str
    governor_id: Optional[str] = None
    alliance: Optional[str] = None
    rank: Optional[int] = Field(default=None, ge=1, le=5)


class ScanRow(BaseModel):
    name: str
    governor_id: Optional[str] = None
    alliance: Optional[str] = None
    power: Optional[int] = None
    kill_points: Optional[int] = None
    t1_kills: Optional[int] = None
    t2_kills: Optional[int] = None
    t3_kills: Optional[int] = None
    t4_kills: Optional[int] = None
    t5_kills: Optional[int] = None
    deads: Optional[int] = None
    rss_gathered: Optional[int] = None
    rss_assist: Optional[int] = None
    helps: Optional[int] = None


class ScanIn(BaseModel):
    kind: str = Field(description="power | killpoints | dead | rss")
    captured_at: Optional[str] = Field(default=None, description="YYYY-MM-DD; defaults to today")
    source: str = "manual"
    rows: list[ScanRow] = []


class GiveTitleIn(BaseModel):
    player_id: int
    title: str = Field(description="Justice | Duke | Architect | Scientist")


class ChangeRankIn(BaseModel):
    player_id: int
    new_rank: int = Field(ge=1, le=5)


class LocateIn(BaseModel):
    player_id: int


class ScanJobIn(BaseModel):
    kind: str = Field(default="power", description="power | killpoints | dead")
    pages: int = Field(default=4, ge=1, le=50, description="rankings pages to scroll")


class RotationIn(BaseModel):
    title: str = Field(description="Justice | Duke | Architect | Scientist")
    player_ids: list[int] = Field(description="governors to cycle, in order")
    hold_seconds: int = Field(default=180, ge=0, le=3600,
                              description="seconds each governor holds the title")


class ScheduleIn(BaseModel):
    kind: str = Field(description="power | killpoints | dead")
    at_hour: int = Field(ge=0, le=23)
    at_minute: int = Field(default=0, ge=0, le=59)
    pages: int = Field(default=4, ge=1, le=50)


class EventIn(BaseModel):
    name: str
    start_date: str = Field(description="YYYY-MM-DD")
    end_date: str = Field(description="YYYY-MM-DD")
