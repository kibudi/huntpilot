"""MongoDB documents for huntpilot."""

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any

import pymongo
from beanie import Document
from pydantic import BaseModel, Field


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


class ProfileSlot(StrEnum):
    """Which stored profile a document holds, of which there is exactly one.

    A single-valued enum rather than no field at all, because a uniqueness index needs something to
    be unique on and "the stored profile" has to mean one document. Two would be produced by the
    API and the worker starting against a fresh database at the same moment, and from then on a
    read would return whichever the driver reached first while an edit changed the other.

    One value because the set really is closed at one: named or per-user profiles are not a feature
    of this tool, so any other value would be a bug rather than a case to handle.
    """

    ACTIVE = "active"


class SweepState(StrEnum):
    """Where one recorded sweep got to.

    Four values, each of which is something that actually happens:

    ``RUNNING`` is written before the first board is read, so a sweep is visible while it is
    happening rather than only once it is over — the whole reason a run is a document.

    ``COMPLETED`` means the pass finished. It covers a sweep in which individual boards failed,
    because that is the normal case rather than an outcome: a failed board is contained by design
    and already counted in ``SweepSummary.boards_failed``, so a separate "partial" state would
    duplicate a number the summary publishes and force clients to read both.

    ``FAILED`` is the opposite: the sweep itself could not finish, so there is no summary at all.
    The stored profile no longer validating is the way this happens in practice, and it is not
    attributable to a board. Note that a sweep felled by the database itself mostly cannot reach
    this state — writing ``FAILED`` is a database write — so it goes to ``ABANDONED`` instead.

    ``ABANDONED`` is a sweep whose process stopped without saying so — a killed container, a
    restarted worker. Nothing can write a final state at that moment by definition, so it is
    written later, by the next attempt to start a sweep, once the run is older than any sweep
    could take. Without it a dead run would sit in ``RUNNING`` for ever and refuse every sweep
    after it.
    """

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ABANDONED = "abandoned"


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


class SearchProfile(Document):
    """The search every filter is currently run against, as stored rather than as committed.

    ``profile.json`` stays in the repository as the default and the worked example, but it cannot
    be what a sweep reads once the dashboard can edit the search: a file is read at startup, so an
    edit would only take effect at the next restart, and the API has no business writing into its
    own package directory. The file therefore seeds this document once, and this document is the
    source of truth from then on.

    ``search`` holds the profile in exactly the form the file writes — every pattern still a
    string — rather than as eight typed fields. The rules that make a profile usable live in
    ``Profile``, which compiles every pattern and refuses an empty whitelist, and restating its
    fields here would be a second, weaker copy of that shape: one that could silently drop a field
    ``Profile`` gained, and that would still not be the validation. Nothing writes this field
    without validating through ``Profile`` first, so the untyped dict is never arbitrary.
    """

    slot: ProfileSlot = ProfileSlot.ACTIVE
    search: dict[str, Any]
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    class Settings:
        """Collection name and the index that keeps the stored profile singular.

        The uniqueness rule is the point of ``slot``: with it, a second process seeding a fresh
        database concurrently is refused by the database rather than producing a rival profile
        that half the reads would return.
        """

        name = "search_profiles"
        indexes = [
            pymongo.IndexModel(
                [("slot", pymongo.ASCENDING)],
                name="one_profile",
                unique=True,
            ),
        ]


class BoardFailure(BaseModel):
    """One board that could not be read during a sweep, and why.

    The company is identified by ATS and token as well as by name, because the name is only a
    label while that pair is what addresses the board — it is the pair to check when a failure
    turns out to be a wrong token rather than an outage.
    """

    name: str
    ats: ATS
    token: str
    error: str


class SweepSummary(BaseModel):
    """What one pass over the whole watchlist did.

    The posting counts are ``SweepResult`` totalled across the boards that were actually read.
    They are reported alongside ``boards_failed`` rather than on their own for a reason: a sweep
    where half the boards failed produces small, honest-looking counts, and only the failure count
    says that the sweep saw half the market.

    It lives here rather than in ``sweep`` because it is stored: it is what a ``SweepRun`` records.
    A sweep returns the same shape it is filed under, so the numbers a pass reports and the numbers
    a client later reads cannot drift apart.
    """

    boards_swept: int = 0
    boards_failed: int = 0
    added: int = 0
    still_open: int = 0
    closed: int = 0
    reopened: int = 0
    failures: list[BoardFailure] = Field(default_factory=list)


class SweepRun(Document):
    """One sweep of the watchlist, from the moment it started to whatever became of it.

    A sweep takes minutes and used to leave nothing behind but a Celery result, which meant the
    only way to know one was happening was to watch the logs. Recording it as a document is what
    lets a dashboard start a sweep and then poll for its progress, and it gives the scheduled
    sweeps a history — how long a pass takes, which boards keep failing — that the counts printed
    to a terminal never accumulated.

    Written by both paths that can sweep, the scheduled task and a manual trigger, so the history
    is the whole history rather than the half that went through one of them.

    ``summary`` is null until the pass is over, rather than zeroed. A sweep still reading its first
    board and a finished sweep that stored nothing are different facts, and zeros would report them
    identically.

    ``error`` is the sweep failing as a whole, which is not the same as a board failing: a board
    that could not be read is contained, counted in the summary, and leaves the run completed.
    """

    state: SweepState = SweepState.RUNNING
    started_at: datetime = Field(default_factory=_now)
    finished_at: datetime | None = None
    summary: SweepSummary | None = None
    error: str | None = None

    class Settings:
        """Collection name, the order runs are read in, and the index that keeps sweeps singular.

        ``started_at`` rather than ``finished_at``, because a run that is still going has no
        finish and must still sort into the list — at the top, where it is the thing being watched.

        The uniqueness rule is what actually prevents two sweeps at once. Asking whether one is
        running and then inserting a run are two round trips, and two triggers arriving together
        both read "no" before either writes — so the check can only ever be advisory and the
        database has to be the one that refuses. Two passes reconciling the same postings would
        each read the other's writes as board state, which is the one failure this collection
        exists to make impossible.

        The index is *partial* rather than plain, because uniqueness is wanted on exactly one
        value: every finished run is also ``state``-valued, and a plain unique index would let one
        sweep ever complete and then refuse the second.
        """

        name = "sweep_runs"
        indexes = [
            [("started_at", pymongo.DESCENDING)],
            pymongo.IndexModel(
                [("state", pymongo.ASCENDING)],
                name="one_running_sweep",
                unique=True,
                partialFilterExpression={"state": SweepState.RUNNING.value},
            ),
        ]
