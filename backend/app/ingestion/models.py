from __future__ import annotations

from datetime import date, datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SYMBOL_MAX_LEN = 15
PROVIDER_MAX_LEN = 40


def _clean_symbol(value: str) -> str:
    return value.strip().upper()


class PriceBar(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    symbol: str = Field(min_length=1, max_length=SYMBOL_MAX_LEN)
    bar_date: date
    open: float = Field(ge=0)
    high: float = Field(ge=0)
    low: float = Field(ge=0)
    close: float = Field(ge=0)
    adjusted_close: float = Field(ge=0)
    volume: int = Field(ge=0)
    provider: str = Field(default="unknown", max_length=PROVIDER_MAX_LEN)

    @field_validator("symbol")
    @classmethod
    def _normalize_symbol(cls, value: str) -> str:
        return _clean_symbol(value)

    @model_validator(mode="after")
    def _check_ohlc(self) -> "PriceBar":
        if self.high < self.low:
            raise ValueError(f"high ({self.high}) is below low ({self.low})")
        if not (self.low <= self.open <= self.high):
            raise ValueError(f"open ({self.open}) outside [low, high]")
        if not (self.low <= self.close <= self.high):
            raise ValueError(f"close ({self.close}) outside [low, high]")
        return self


class TickerMetadata(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    symbol: str = Field(min_length=1, max_length=SYMBOL_MAX_LEN)
    company_name: str | None = None
    sector: str | None = None
    industry: str | None = None
    exchange: str | None = None
    market_cap: int | None = Field(default=None, ge=0)
    business_summary: str | None = None
    provider: str = Field(default="unknown", max_length=PROVIDER_MAX_LEN)

    @field_validator("symbol")
    @classmethod
    def _normalize_symbol(cls, value: str) -> str:
        return _clean_symbol(value)


class SearchResult(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1)
    url: str | None = None
    normalized_url: str | None = None
    content: str | None = None
    raw_content: str | None = None
    source_domain: str | None = None
    score: float | None = Field(default=None, ge=0, le=1)
    published_at: datetime | None = None
    query_text: str | None = None
    provider: str = Field(default="tavily", max_length=PROVIDER_MAX_LEN)

    @field_validator("published_at")
    @classmethod
    def _to_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @property
    def is_dated(self) -> bool:
        return self.published_at is not None

    @property
    def published_date(self) -> date | None:
        return self.published_at.date() if self.published_at else None
