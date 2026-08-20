"""Pydantic schemas describing what the API sends over the wire.

These exist so the HTTP contract is stated separately from how documents are stored. Returning
Beanie Documents directly leaks MongoDB's key name — the JSON field is ``_id`` rather than ``id`` —
and makes FastAPI reuse one input-shaped schema for output, which marks always-present fields
optional and forces clients into null checks that can never be true.
"""

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, ClassVar

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from app.models import ATS, PostingStatus, Status, SweepState, SweepSummary

ObjectIdStr = Annotated[str, BeforeValidator(str)]
"""A MongoDB ObjectId rendered as a string, since JSON has no such type.

The validator converts whatever arrives, which is what lets ``model_validate`` read the ObjectId
straight off a document. The declared type is still ``str``, so a caller building the schema by
keyword instead has to convert first — Beanie types ``id`` as ``PydanticObjectId | None`` and the
type checker compares against the declaration, not the validator. The conversion at such a call
site is therefore not redundant with this one.
"""


class Region(StrEnum):
    """Where a posting can be worked from, as the API reports it.

    Two values and no third, because only postings that passed ``in_scope_location`` are ever
    stored: a location naming nowhere in Israel is in storage because it advertised as remote.
    An "elsewhere" value would describe a posting the sweep never keeps.

    It lives here rather than on the document because nothing stores it. It is derived from
    ``location_raw`` on the way out, so that the one list of Israeli spellings stays in the
    backend and clients count Israeli roles by reading a field rather than by re-implementing
    the list and drifting from it.
    """

    ISRAEL = "israel"
    REMOTE = "remote"


class ApplicationCreate(BaseModel):
    """Fields a client may supply when tracking a new application.

    ``id``, ``created_at`` and ``updated_at`` are absent deliberately: they are the server's to
    assign, and ``extra="forbid"`` makes an attempt to set them a 422 rather than a silently
    ignored field. The same rule catches a misspelled field name, which a schemaless database
    would otherwise store as a new key that no query ever matches.

    The fields with defaults here are the same ones ``ApplicationRead`` marks required, which is
    the reason the two schemas exist separately: optional to send, guaranteed to receive.
    """

    model_config = ConfigDict(extra="forbid")

    company: str
    role: str
    location: str
    source: str
    url: str
    status: Status = Status.SAVED
    applied_date: date | None = None
    notes: str = ""


class ApplicationUpdate(BaseModel):
    """Fields a client may change on an existing application.

    Every field is optional so a status can be moved without resending the rest. Only fields
    actually present in the request body are applied — a field left out is untouched, which is
    what distinguishes a PATCH from a replacement.

    ``applied_date`` is the only field that may be set to null, to undo a date entered by mistake.
    Sending null for any other field is rejected rather than storing a null the document cannot
    hold.
    """

    model_config = ConfigDict(extra="forbid")

    company: str | None = None
    role: str | None = None
    location: str | None = None
    source: str | None = None
    url: str | None = None
    status: Status | None = None
    applied_date: date | None = None
    notes: str | None = None

    NULLABLE_FIELDS: ClassVar[frozenset[str]] = frozenset({"applied_date"})

    @model_validator(mode="after")
    def _reject_null_on_non_nullable_fields(self) -> "ApplicationUpdate":
        """Refuses an explicit null for any field the document stores as non-optional.

        ``model_fields_set`` is what separates a field the client sent as null from one it simply
        omitted; both look like ``None`` on the model itself.

        Raises:
            ValueError: If a non-nullable field was explicitly set to null.
        """
        for name in self.model_fields_set - self.NULLABLE_FIELDS:
            if getattr(self, name) is None:
                raise ValueError(f"{name} may not be null")
        return self


class ApplicationRead(BaseModel):
    """A tracked application as returned by the API.

    Every field is required: a stored document always has all of them, so clients never need a
    null check except on ``applied_date``, which is genuinely absent until a job is applied to.
    """

    model_config = ConfigDict(from_attributes=True)

    id: ObjectIdStr
    company: str
    role: str
    location: str
    source: str
    url: str
    status: Status
    applied_date: date | None
    notes: str
    created_at: datetime
    updated_at: datetime


class PostingRead(BaseModel):
    """A posting swept from a company's board, as returned by the API.

    ``company`` is the watchlist entry's display name, not the ``company_token`` the posting
    stores. The token is the company's slug inside its ATS — "catonetworks" rather than "Cato
    Networks" — and it exists so a URL can be built, which is no reason to make a reader decode
    it. ``location`` likewise drops the ``_raw`` of ``location_raw``: the suffix records that the
    three boards format locations differently and nothing has normalised them, which is a storage
    concern rather than something the field name should tell a client.

    ``external_id``, ``company_token`` and ``missed_sweeps`` are deliberately absent. They are the
    sweep's own bookkeeping — a board's internal identifier, the slug it is addressed by, and a
    counter that only means anything between a posting's first absence and its closure — and
    publishing them would invite clients to depend on mechanics that exist precisely so they can
    change.

    ``region`` is derived from the same ``location_raw`` that ``location`` reports verbatim. Both
    are published because they answer different questions: the raw text is what a reader wants to
    see, while the region is what a client filters and counts on, and deriving one from the other
    client-side means every client keeping its own copy of the spellings that place a posting in
    Israel.

    ``closed_at`` is the only nullable field: a posting still listed has not closed, so there is
    no instant to report. Every other field is present on any stored posting.
    """

    id: ObjectIdStr
    company: str
    ats: ATS
    title: str
    location: str
    region: Region
    url: str
    status: PostingStatus
    first_seen_at: datetime
    last_seen_at: datetime
    closed_at: datetime | None


class ProfileBody(BaseModel):
    """The search profile as it travels in both directions: every pattern still a string.

    The one schema in this file used for a request *and* a response, against the rule that separates
    the two. The rule exists because ``id``, ``created_at`` and ``updated_at`` are forbidden on
    input and guaranteed on output, and a profile publishes none of them: it is a singleton, so an
    identifier says nothing a client can use, and the timestamps belong to the row rather than to
    the search. With nothing asymmetric left, two classes would be one shape written twice — and
    the symmetry is worth having, because the dashboard's editor is a form filled from ``GET`` and
    posted back to ``PUT``, so anything present in one direction and absent in the other is a trap.

    Deliberately carries the *shape* and not the rules. There are no minimum lengths or bounds
    here, even though ``Profile`` has several: this says what a profile looks like so FastAPI can
    describe and parse it, while ``Profile`` decides whether it is a search worth running. Copying
    the constraints would give two answers to that question, and the copy is the one that would
    fall behind.

    Patterns are strings, exactly as ``profile.json`` writes them, because that is what a person
    edits and what JSON can carry. They are compiled on the way in, and a broken one comes back as
    a rejection naming the technology or family it belongs to.

    Field order matches ``Profile``: ``role_families`` is tried in the order given, so the order a
    client sends is a decision it is making.
    """

    model_config = ConfigDict(extra="forbid")

    local_fragments: list[str]
    remote_fragments: list[str]
    seniority_markers: str
    role_families: dict[str, str]
    known: dict[str, str]
    unknown: dict[str, str] = Field(default_factory=dict)
    min_tech_score: float
    max_years: int


class SweepRunRead(BaseModel):
    """One recorded sweep as the API reports it.

    ``summary`` and ``finished_at`` are null exactly while the sweep is running, and both are
    filled the moment it is not — so a client polling this has one thing to test rather than a
    state to interpret. ``error`` is the reverse: null unless the pass could not be completed at
    all.

    ``SweepSummary`` is published as it is stored rather than restated as a response schema of its
    own. The two reasons the other schemas here exist do not apply to it: it has no ``_id``, and
    every one of its fields is required with a default, so it is already the same shape in both
    directions. Copying it would mean the numbers a sweep counts and the numbers a client reads
    could drift.
    """

    model_config = ConfigDict(from_attributes=True)

    id: ObjectIdStr
    state: SweepState
    started_at: datetime
    finished_at: datetime | None
    summary: SweepSummary | None
    error: str | None
