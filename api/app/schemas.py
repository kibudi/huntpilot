"""Pydantic schemas describing what the API sends over the wire.

These exist so the HTTP contract is stated separately from how documents are stored. Returning
Beanie Documents directly leaks MongoDB's key name — the JSON field is ``_id`` rather than ``id`` —
and makes FastAPI reuse one input-shaped schema for output, which marks always-present fields
optional and forces clients into null checks that can never be true.
"""

from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict

from app.models import Status

ObjectIdStr = Annotated[str, BeforeValidator(str)]
"""A MongoDB ObjectId rendered as a string, since JSON has no such type."""


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
