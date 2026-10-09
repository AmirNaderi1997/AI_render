from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from urllib.parse import urlparse


def aware(value):
    if value is not None and value.tzinfo is None:
        raise ValueError("A timezone offset is required")
    return value


class PostCreate(BaseModel):
    account_id: str
    caption: str = Field(default="", max_length=2200)
    hashtags: list[str] = Field(default_factory=list, max_length=30)
    media_urls: list[str] = Field(default_factory=list, max_length=10)
    scheduled_at: datetime | None = None

    _tz = field_validator("scheduled_at")(aware)

    @field_validator("media_urls")
    @classmethod
    def public_urls(cls, values):
        if any(urlparse(value).scheme != "https" or not urlparse(value).hostname for value in values):
            raise ValueError("Media URLs must be public HTTPS URLs")
        return values

    @model_validator(mode="after")
    def scheduled_media(self):
        if self.scheduled_at and not self.media_urls:
            raise ValueError("Scheduled posts require media")
        return self

    @field_validator("hashtags")
    @classmethod
    def clean_tags(cls, values):
        return [value.lstrip("#").strip() for value in values if value.strip()]


class PostUpdate(BaseModel):
    caption: str | None = Field(default=None, max_length=2200)
    hashtags: list[str] | None = Field(default=None, max_length=30)
    media_urls: list[str] | None = Field(default=None, max_length=10)
    scheduled_at: datetime | None = None

    _tz = field_validator("scheduled_at")(aware)

    @field_validator("caption", "hashtags", "media_urls", mode="before")
    @classmethod
    def non_nullable_post_fields(cls, value):
        if value is None:
            raise ValueError("field may be omitted but cannot be null")
        return value

    @field_validator("media_urls")
    @classmethod
    def public_urls(cls, values):
        return PostCreate.public_urls(values) if values is not None else None


class BulkItem(BaseModel):
    post_id: str
    scheduled_at: datetime

    _tz = field_validator("scheduled_at")(aware)


class BulkSchedule(BaseModel):
    items: list[BulkItem] = Field(min_length=1, max_length=100)


class AccountRef(BaseModel):
    account_id: str


class BestTimesRequest(AccountRef):
    timezone: str = "Asia/Tehran"
    topic: str = Field(default="", max_length=1000)


class HashtagsRequest(AccountRef):
    content: str = Field(min_length=1, max_length=4000)
    count: int = Field(default=10, ge=1, le=30)


class CaptionRequest(AccountRef):
    content: str = Field(min_length=1, max_length=4000)
    tone: str = Field(default="natural", max_length=100)


class ContentPlanRequest(AccountRef):
    topic: str = Field(min_length=1, max_length=2000)
    timezone: str = "Asia/Tehran"
    posts_per_week: int = Field(default=5, ge=1, le=7)
