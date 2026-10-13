"""Database tables for users and future job, style, and content persistence."""

from typing import Optional

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class UserModel(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[str] = mapped_column(String(50))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    refresh_tokens: Mapped[list[str]] = mapped_column(JSON, default=list)
    reset_token: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    reset_expires: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="new")
    stage: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    message: Mapped[str] = mapped_column(Text, default="")
    progress_pct: Mapped[int] = mapped_column(Integer, default=0)
    source_path: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    # Compatibility state keeps the public job JSON stable while its canonical
    # persistence moves out of the old status.json sidecar.
    state: Mapped[dict] = mapped_column(JSON, default=dict)
    # Keep the original migration's ISO-string timestamp representation so
    # existing installations upgrade without an in-place type rewrite.
    created_at: Mapped[str] = mapped_column(String(50), default=lambda: datetime.utcnow().isoformat())
    updated_at: Mapped[Optional[str]] = mapped_column(String(50), nullable=True,
                                                       onupdate=lambda: datetime.utcnow().isoformat())


# Backwards-compatible import name for the existing auth/content code.
JobModel = Job


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), unique=True, index=True)
    scenes: Mapped[list] = mapped_column(JSON, default=list)
    captions: Mapped[list] = mapped_column(JSON, default=list)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class PlanVersion(Base):
    """Immutable snapshot of a job's plan after each change (undo history)."""

    __tablename__ = "plan_versions"
    __table_args__ = (UniqueConstraint("job_id", "version", name="uq_plan_versions_job_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    parent_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # ai_generate | user_ui | chat | qc | undo | legacy
    source: Mapped[str] = mapped_column(String(32))
    operations: Mapped[list] = mapped_column(JSON, default=list)
    plan: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class RenderResult(Base):
    __tablename__ = "render_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    output_path: Mapped[str] = mapped_column(String(1000))
    format: Mapped[str] = mapped_column(String(50), default="mp4")
    duration: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class QCResult(Base):
    __tablename__ = "qc_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    scores: Mapped[dict] = mapped_column(JSON, default=dict)
    issues: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class StyleProfileModel(Base):
    __tablename__ = "style_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(255))
    profile_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String(50))


class StyleReference(Base):
    """One analyzed reference reel used to build a user's learned style."""

    __tablename__ = "style_references"
    __table_args__ = (UniqueConstraint("user_id", "digest", name="uq_style_references_user_digest"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    digest: Mapped[str] = mapped_column(String(32))
    source_file: Mapped[str] = mapped_column(String(500), default="")
    analysis: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class LearnedStyleProfile(Base):
    """A user's merged learned style profile (one row per user)."""

    __tablename__ = "learned_style_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True, unique=True)
    profile: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class PlanStyleSelection(Base):
    """A user's default approved visual style for newly generated plans."""

    __tablename__ = "plan_style_selections"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    style_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class PlanStyleVisibility(Base):
    """User choice to hide the built-in defaults card, not the render preset."""

    __tablename__ = "plan_style_visibility"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    default_hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class ContentRequestModel(Base):
    __tablename__ = "content_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    prompt: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(50), default="pending")
    job_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    created_at: Mapped[str] = mapped_column(String(50))
