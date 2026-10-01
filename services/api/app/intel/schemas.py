"""Pydantic models for intelligence artifacts — the server-side authority.
The web contract mirrors these in packages/contracts (camelCase aliases,
matching the API's JSON convention)."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class Source(BaseModel):
    idx: int
    title: str
    url: str
    publisher: str
    published_at: str | None = Field(default=None, serialization_alias="publishedAt")
    quality: Literal["high", "medium", "low"] = "medium"

    model_config = {"populate_by_name": True}


class CasePoint(BaseModel):
    claim: str
    citation: int | None = None


class Catalyst(BaseModel):
    what: str
    when_hint: str = Field(default="", serialization_alias="whenHint")
    citation: int | None = None

    model_config = {"populate_by_name": True}


class Brief(BaseModel):
    headline: str
    summary: str
    bullish: list[CasePoint] = []
    bearish: list[CasePoint] = []
    catalysts: list[Catalyst] = []
    source_note: str = Field(default="", serialization_alias="sourceNote")
    sources: list[Source] = []

    model_config = {"populate_by_name": True}

    @field_validator("bullish", "bearish")
    @classmethod
    def _cap_points(cls, v: list[CasePoint]) -> list[CasePoint]:
        if len(v) > 6:
            raise ValueError("too many case points")
        return v

    def cite(self, idx: int | None) -> bool:
        """A citation is valid only if it points at a fetched source."""
        return idx is None or any(s.idx == idx for s in self.sources)


class Driver(BaseModel):
    kind: Literal["trade_flow", "news", "lifecycle", "liquidity", "other"] = "other"
    weight: float = 0.5
    evidence: str


class Explanation(BaseModel):
    narrative: str
    drivers: list[Driver] = []
    confidence: Literal["low", "medium", "high"] = "medium"
