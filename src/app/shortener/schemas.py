from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.shortener.validation import normalize_destination_url, validate_short_code


class CreateLinkRequest(BaseModel):
    original_url: str = Field(max_length=2048, examples=["https://example.com/long-path"])
    custom_alias: str | None = Field(default=None, max_length=32, examples=["example"])
    expires_at: datetime | None = None

    @field_validator("original_url")
    @classmethod
    def validate_original_url(cls, value: str) -> str:
        return normalize_destination_url(value)

    @field_validator("custom_alias")
    @classmethod
    def validate_custom_alias(cls, value: str | None) -> str | None:
        return validate_short_code(value) if value is not None else None


class UpdateLinkRequest(BaseModel):
    original_url: str | None = Field(default=None, max_length=2048)
    expires_at: datetime | None = None
    is_enabled: bool | None = None

    @field_validator("original_url")
    @classmethod
    def validate_original_url(cls, value: str | None) -> str | None:
        return normalize_destination_url(value) if value is not None else None


class LinkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    short_code: str
    short_url: str
    original_url: str
    is_enabled: bool
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None
    last_accessed_at: datetime | None


class AnalyticsDay(BaseModel):
    date: str
    clicks: int


class LinkAnalyticsResponse(BaseModel):
    short_code: str
    total_clicks: int
    last_accessed_at: datetime | None
    clicks_by_day: list[AnalyticsDay]
