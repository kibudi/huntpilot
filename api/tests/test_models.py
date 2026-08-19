"""Tests for the Application document's defaults, validation, and storage format."""

from datetime import UTC, date
from typing import Any

import pytest
from conftest import PAYLOAD
from pydantic import ValidationError
from pymongo import AsyncMongoClient

from app.models import Application, Status


async def test_applies_defaults(db: AsyncMongoClient[dict[str, Any]]) -> None:
    """A document created with only the required fields is complete."""
    saved = await Application(**PAYLOAD).insert()

    assert saved.status is Status.SAVED
    assert saved.notes == ""
    assert saved.applied_date is None
    assert saved.created_at.tzinfo is not None


async def test_rejects_unknown_status(db: AsyncMongoClient[dict[str, Any]]) -> None:
    """A status outside the enum is refused before it reaches the database."""
    with pytest.raises(ValidationError):
        Application(**PAYLOAD | {"status": "banana"})


async def test_rejects_misspelled_field(db: AsyncMongoClient[dict[str, Any]]) -> None:
    """A typo'd field name is refused rather than silently stored as a new field.

    This is the failure mode a schemaless database would otherwise accept: the document would save
    with a `comapny` key and every later query on `company` would miss it.
    """
    fields = PAYLOAD | {"comapny": "Gong"}
    del fields["company"]

    with pytest.raises(ValidationError):
        Application(**fields)


async def test_stores_status_as_plain_string(db: AsyncMongoClient[dict[str, Any]]) -> None:
    """Status persists as its lowercase value, so raw mongosh queries match."""
    await Application(**PAYLOAD | {"status": Status.APPLIED}).insert()

    raw = await Application.get_pymongo_collection().find_one({})

    assert raw is not None
    assert raw["status"] == "applied"


async def test_applied_date_round_trips(db: AsyncMongoClient[dict[str, Any]]) -> None:
    """A date survives the trip through BSON, which has no date type of its own.

    MongoDB stores it as a datetime at midnight; Beanie converts it back on read. Raw queries
    therefore have to use datetimes rather than a date string.
    """
    await Application(
        **PAYLOAD | {"status": Status.APPLIED, "applied_date": date(2026, 7, 15)}
    ).insert()

    fetched = await Application.find_one({})
    raw = await Application.get_pymongo_collection().find_one({})

    assert fetched is not None
    assert fetched.applied_date == date(2026, 7, 15)
    assert raw is not None
    assert raw["applied_date"].hour == 0


async def test_timestamps_are_utc(db: AsyncMongoClient[dict[str, Any]]) -> None:
    """Timestamps come back with an offset rather than naive.

    BSON stores no offset, so this only holds because the client is created with ``tz_aware=True``.
    Without it a consumer in any non-UTC zone reads the value as local time and computes an age
    hours wrong.
    """
    await Application(**PAYLOAD).insert()

    fetched = await Application.find_one({})

    assert fetched is not None
    assert fetched.created_at.tzinfo is not None
    assert fetched.created_at.utcoffset() == UTC.utcoffset(None)
