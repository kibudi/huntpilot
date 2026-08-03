"""Pydantic schemas describing what the API sends over the wire.

These exist so the HTTP contract is stated separately from how documents are stored. Returning
Beanie Documents directly leaks MongoDB's key name — the JSON field is ``_id`` rather than ``id`` —
and makes FastAPI reuse one input-shaped schema for output, which marks always-present fields
optional and forces clients into null checks that can never be true.
"""

from datetime import date, datetime
from typing import Annotated, ClassVar

from pydantic import BaseModel, BeforeValidator, ConfigDict, model_validator

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
