"""Hermes tables share the main application's SQLAlchemy metadata and users table."""
from datetime import date, datetime, timezone

from sqlalchemy import JSON, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base, UserModel  # registers the users FK on shared metadata


def now() -> datetime:
    return datetime.now(timezone.utc)


class InstagramAccount(Base):
    __tablename__ = "hermes_instagram_accounts"
    __table_args__ = (UniqueConstraint("user_id", "ig_user_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    ig_user_id: Mapped[str] = mapped_column(String(100))
    username: Mapped[str] = mapped_column(String(255))
    access_token: Mapped[str] = mapped_column(Text)  # Fernet ciphertext only
    token_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class HermesSetting(Base):
    """Per-user provider credentials; every value inside encrypted_credentials is Fernet ciphertext."""
    __tablename__ = "hermes_settings"
    __table_args__ = (UniqueConstraint("user_id", "provider"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(30))
    encrypted_credentials: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ScheduledPost(Base):
    __tablename__ = "hermes_scheduled_posts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("hermes_instagram_accounts.id"), index=True)
    caption: Mapped[str] = mapped_column(Text, default="")
    hashtags: Mapped[list] = mapped_column(JSON, default=list)
    media_urls: Mapped[list] = mapped_column(JSON, default=list)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    ig_post_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class PostAnalytics(Base):
    __tablename__ = "hermes_post_analytics"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    post_id: Mapped[str] = mapped_column(ForeignKey("hermes_scheduled_posts.id"), index=True)
    ig_post_id: Mapped[str] = mapped_column(String(100))
    impressions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reach: Mapped[int | None] = mapped_column(Integer, nullable=True)
    likes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comments: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shares: Mapped[int | None] = mapped_column(Integer, nullable=True)
    saves: Mapped[int | None] = mapped_column(Integer, nullable=True)
    engagement_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AccountInsight(Base):
    __tablename__ = "hermes_account_insights"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("hermes_instagram_accounts.id"), index=True)
    date: Mapped[date] = mapped_column(Date)
    followers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    follows: Mapped[int | None] = mapped_column(Integer, nullable=True)
    impressions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reach: Mapped[int | None] = mapped_column(Integer, nullable=True)
    profile_views: Mapped[int | None] = mapped_column(Integer, nullable=True)
    website_clicks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AdvisorLog(Base):
    __tablename__ = "hermes_advisor_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("hermes_instagram_accounts.id"), index=True)
    request_type: Mapped[str] = mapped_column(String(30))
    input_data: Mapped[dict] = mapped_column(JSON)
    recommendation: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


TABLES = {
    "accounts": InstagramAccount,
    "settings": HermesSetting,
    "posts": ScheduledPost,
    "post_analytics": PostAnalytics,
    "account_insights": AccountInsight,
    "advisor_logs": AdvisorLog,
}
