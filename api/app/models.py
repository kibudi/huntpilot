"""SQLAlchemy models for huntpilot."""

from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import DateTime, func, text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


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


class Base(DeclarativeBase):
    """Declarative base for all huntpilot tables.

    ``type_annotation_map`` sets, once, what two annotations mean everywhere:

    ``datetime`` becomes TIMESTAMP WITH TIME ZONE, so timestamps carry an offset instead of being
    naive wall-clock readings.

    ``Status`` becomes an enum whose database labels are the lowercase member values ("saved")
    rather than SQLAlchemy's default of member names ("SAVED"). Without ``values_callable`` the
    database and the API would speak different vocabularies, and ``WHERE status = 'saved'`` in a
    psql session would match nothing.
    """

    type_annotation_map = {
        datetime: DateTime(timezone=True),
        Status: SAEnum(
            Status,
            name="application_status",
            values_callable=lambda cls: [member.value for member in cls],
        ),
    }


class Application(Base):
    """A single job application being tracked.

    The timestamps are the sort keys the dashboard and bot order by: ``created_at`` for when a job
    was first saved, ``updated_at`` for the last time anything about it moved. Both are indexed.

    Every column carries a server default, so a row inserted by any client — a seed script, a psql
    session, the future worker — is complete and sorts correctly. ``updated_at`` is the exception:
    ``onupdate`` is applied by SQLAlchemy when it builds the UPDATE, not by Postgres, so a write
    that bypasses SQLAlchemy will leave it stale. Keeping ``api/`` the sole writer is what makes
    that safe; a database trigger would be needed otherwise.
    """

    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(primary_key=True)
    company: Mapped[str]
    role: Mapped[str]
    location: Mapped[str]
    source: Mapped[str]
    url: Mapped[str]
    status: Mapped[Status] = mapped_column(
        default=Status.SAVED, server_default=text("'saved'")
    )
    applied_date: Mapped[date | None] = mapped_column(index=True)
    notes: Mapped[str] = mapped_column(default="", server_default=text("''"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), index=True
    )
