"""SQLAlchemy models for huntpilot."""

from datetime import date
from enum import StrEnum

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for all huntpilot tables."""


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
    """A single job application being tracked."""

    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(primary_key=True)
    company: Mapped[str]
    role: Mapped[str]
    location: Mapped[str]
    source: Mapped[str]
    url: Mapped[str]
    status: Mapped[Status]
    applied_date: Mapped[date | None]
    notes: Mapped[str]
