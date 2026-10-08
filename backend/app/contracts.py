from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, field_validator


class Advisory(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    provider: Literal["NHC", "NWS", "TRAINING"]
    event_key: str
    title: str
    issued_at: datetime
    expires_at: datetime | None = None
    source_url: str
    provenance: Literal["official_fetch", "manual_import", "synthetic_fixture"]
    severity: str = "Unknown"
    area: str = ""
    facts: dict[str, str | float | int | None] = Field(default_factory=dict)
    text: str
    checksum: str = ""
    references: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    forecast_excerpt: str | None = None
    source_feed_url: str | None = None
    source_payload: dict | None = None

    @field_validator("issued_at", "expires_at")
    @classmethod
    def aware_utc(cls, value):
        if value is None:
            return value
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Source timestamps must include a timezone.")
        return value.astimezone(timezone.utc)


class ImportRequest(BaseModel):
    text: str = Field(min_length=100, max_length=100_000)
    source_url: str = Field(max_length=1000)


class FetchRequest(BaseModel):
    source_url: str = Field(max_length=1000)


class ScriptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    advisory_id: str
    engine: Literal['deterministic', 'ollama', 'gemini'] = 'deterministic'
    refresh_sources: bool = False


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reviewer: str = Field(min_length=2, max_length=100)
    expected_revision: int | None = Field(default=None, ge=1)
    note: str = Field(default='', max_length=2000)

    @field_validator('reviewer')
    @classmethod
    def named(cls, value):
        if len(value.strip()) < 2:
            raise ValueError('A reviewer name is required.')
        return value.strip()


class EditRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_revision: int = Field(ge=1)
    text: str = Field(min_length=50, max_length=60_000)
    editor: str = Field(min_length=2, max_length=100)
    note: str = Field(min_length=3, max_length=2000)

    @field_validator('editor', 'note')
    @classmethod
    def not_blank(cls, value):
        if len(value.strip()) < 2:
            raise ValueError('An editor name and revision note are required.')
        return value.strip()


class ClaimSupportRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_revision: int = Field(ge=1)
    claim_id: str
    advisory_id: str
    quote: str = Field(min_length=20, max_length=15_000)
    explanation: str = Field(min_length=10, max_length=2000)
    reviewer: str = Field(min_length=2, max_length=100)

    @field_validator('reviewer', 'explanation')
    @classmethod
    def not_blank(cls, value):
        if len(value.strip()) < 2:
            raise ValueError('Named source verification and an explanation are required.')
        return value.strip()


class Change(BaseModel):
    field: str
    previous: str | float | int | None
    current: str | float | int | None
    delta: float | None = None


class PollingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    interval_seconds: int = Field(default=300, ge=60, le=3600)
