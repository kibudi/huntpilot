"""MongoDB documents for huntpilot."""

from datetime import UTC, date, datetime
from enum import StrEnum

import pymongo
from beanie import Document
from pydantic import Field


def _now() -> datetime:
    """Returns the current time as a timezone-aware UTC timestamp."""
    return datetime.now(UTC)


class Status(StrEnum):
    """Where an application sits in the pipeline.

    Outcomes are pipeline states rather than a separate field, so an application cannot claim an
    outcome it hasn't reached. Declaration order is pipeline order.
    """

    SAVED = "saved"
    APPLIED = "applied"
    INTERVIEW = "interview"
    OFFER = "offer"
    REJECTED = "rejected"
    GHOSTED = "ghosted"

class Application(Document):
    """A single job application being tracked.

    Beanie supplies the ``id`` field, so it is not declared here.

    The timestamps are the sort keys the dashboard and bot order by: ``created_at`` for when a job
    was first saved, ``updated_at`` for the last time anything about it moved. Both are indexed
    descending, which is the direction they are read in. Unlike a relational database, MongoDB has
    no server-side default or on-update mechanism, so both are set in Python and ``updated_at``
    must be refreshed by whoever saves the document.
    """

    company: str
    role: str
    location: str
    source: str
    url: str
    status: Status = Status.SAVED
    applied_date: date | None = None
    notes: str = ""
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    class Settings:
        """Collection name, the indexes backing the sort keys, and the uniqueness rule on ``url``.

        The uniqueness index is partial rather than plain. A posting link identifies a job, so two
        documents sharing one are the same application recorded twice — but a job found through an
        agency or an undisclosed employer genuinely has no link, and those are stored as ``""``.
        A plain unique index would read every one of those blanks as a duplicate of the others and
        refuse to build, taking the application down with it, so uniqueness is enforced only where
        a link is actually present.

        Sparse would not do instead: it skips documents where the field is missing, and ``url`` is
        always present, merely empty.
        """

        name = "applications"
        indexes = [
            [("created_at", pymongo.DESCENDING)],
            [("updated_at", pymongo.DESCENDING)],
            [("applied_date", pymongo.DESCENDING)],
            pymongo.IndexModel(
                [("url", pymongo.ASCENDING)],
                name="url_unique_when_present",
                unique=True,
                partialFilterExpression={"url": {"$gt": ""}},
            ),
        ]
