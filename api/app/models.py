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


class ATS(StrEnum):
    """The applicant-tracking systems whose public board APIs are readable without a key.

    Comeet is deliberately absent: it serves its boards from JavaScript and its careers API
    requires a per-company token that is never present in the fetched HTML, so it cannot be swept
    the way these three can.
    """

    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    ASHBY = "ashby"


class PostingStatus(StrEnum):
    """Whether a posting was still on its board at the last sweep.

    A board never announces that a role was filled — the entry simply stops being returned. The
    closed state is therefore inferred from absence rather than reported, which is the whole point
    of tracking board state over time.
    """

    OPEN = "open"
    CLOSED = "closed"


class Company(Document):
    """A company whose job board is swept.

    ``token`` is the company's slug in its ATS, which is what the board URL is built from — it is
    not always the company name, so it is stored rather than derived.

    ``last_swept_at`` records when the board was last read successfully. It is the only sweep
    bookkeeping stored here for now; failure counting and an enable/disable flag belong with the
    scheduled job that needs them, which does not exist yet.
    """

    name: str
    ats: ATS
    token: str
    last_swept_at: datetime | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    class Settings:
        """Collection name and the uniqueness rule identifying one board.

        A board is identified by its ATS and token together, never by name: the same token can
        exist on two different systems, and two companies can share a display name. The pair is
        what the sweep looks up, so it is the pair that must be unique.
        """

        name = "companies"
        indexes = [
            pymongo.IndexModel(
                [("ats", pymongo.ASCENDING), ("token", pymongo.ASCENDING)],
                name="board_unique",
                unique=True,
            ),
        ]


class Posting(Document):
    """One posting as last seen on a company's board.

    There is one document per posting for its whole life, not one per sweep. A sweep that finds a
    posting still listed bumps ``last_seen_at`` in place; appending a row each time would grow the
    collection with elapsed time rather than with the market, for no extra signal.

    ``missed_sweeps`` exists because a single absence is not evidence of closure — boards
    intermittently omit live entries, and closing on the first miss would report roles as filled
    that are still open. Closure requires repeated absence.

    ``external_id`` is the board's own identifier for the posting and is the stable key. A
    posting's URL and title can both change while it stays the same opening.

    ``description`` is the posting body as plain text. It is stored rather than the conclusions
    drawn from it, because those conclusions — which technologies were recognised, how many years
    were asked for — depend on a vocabulary that changes as it is corrected. Storing the text
    keeps every stored posting rescorable; storing a score freezes it at the moment of the sweep
    and cannot be revisited without fetching the board again.
    """

    company_token: str
    ats: ATS
    external_id: str
    url: str
    title: str
    location_raw: str
    description: str = ""
    first_seen_at: datetime = Field(default_factory=_now)
    last_seen_at: datetime = Field(default_factory=_now)
    missed_sweeps: int = 0
    closed_at: datetime | None = None
    status: PostingStatus = PostingStatus.OPEN

    class Settings:
        """Collection name and the uniqueness rule identifying one posting.

        Identity is the ATS, the company's token and the board's own posting id together. The
        company token is part of the key because a posting id is only documented to be unique
        within the board that issued it, not across every company on that system.
        """

        name = "postings"
        indexes = [
            pymongo.IndexModel(
                [
                    ("ats", pymongo.ASCENDING),
                    ("company_token", pymongo.ASCENDING),
                    ("external_id", pymongo.ASCENDING),
                ],
                name="posting_unique",
                unique=True,
            ),
        ]


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
