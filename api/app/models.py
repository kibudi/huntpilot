"""SQLAlchemy models for huntpilot."""

from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for all huntpilot tables.

    ``type_annotation_map`` makes every ``Mapped[datetime]`` a TIMESTAMP WITH TIME ZONE, so
    timestamps carry an offset instead of being naive wall-clock readings.
    """

    type_annotation_map = {datetime: DateTime(timezone=True)}


class Status(StrEnum):
    """Where an application sits in the pipeline.

    Outcomes are pipeline states rather than a separate column, so an application cannot claim an
    outcome it hasn't reached. Declaration order is pipeline order.
    """

    SAVED = "saved"
    APPLIED = "applied"
    INTERVIEW = "interview"
    OFFER = "offer"
    REJECTED = "rejected"
    GHOSTED = "ghosted"


class Application(Base):
    """A single job application being tracked.

    The timestamps are the sort keys the dashboard and bot order by: ``created_at`` for when a job
    was first saved, ``updated_at`` for the last time anything about it moved. Both are indexed
    and set by the database rather than by Python, so rows written by any client sort correctly.
    """

    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(primary_key=True)
    company: Mapped[str]
    role: Mapped[str]
    location: Mapped[str]
    source: Mapped[str]
    url: Mapped[str]
    status: Mapped[Status] = mapped_column(default=Status.SAVED)
    applied_date: Mapped[date | None] = mapped_column(index=True)
    notes: Mapped[str] = mapped_column(default="")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), index=True
    )
