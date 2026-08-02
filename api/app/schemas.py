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
