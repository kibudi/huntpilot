"""Tests for how an application is stored and described: the document, its index, its schemas.

The endpoint behaviour built on all of this lives in ``test_applications.py``. What is here is the
shape underneath — defaults, the BSON round trip, the uniqueness rule the database itself enforces,
and the response contract the OpenAPI description publishes.
"""

from datetime import UTC, date
from typing import Any

import pytest
from conftest import PAYLOAD
from httpx import AsyncClient
from pydantic import ValidationError
from pymongo import AsyncMongoClient

from app.models import Application, Status

PUBLISHED_FIELDS = {
    "id",
    "company",
    "role",
    "location",
    "source",
    "url",
    "status",
    "applied_date",
    "notes",
    "created_at",
    "updated_at",
}
"""Exactly the fields the contract publishes, so a leaked storage field fails the test."""


async def test_applies_defaults(db: AsyncMongoClient[dict[str, Any]]) -> None:
    """A document created with only the required fields is complete.

    These are the document's own defaults, not the schema's: the create endpoint always passes a
    value for all three, so nothing on the HTTP path would notice if they were dropped here.
    """
    saved = await Application(**PAYLOAD).insert()

    assert saved.status is Status.SAVED
    assert saved.notes == ""
    assert saved.applied_date is None
    assert saved.created_at.tzinfo is not None


async def test_rejects_a_missing_required_field(db: AsyncMongoClient[dict[str, Any]]) -> None:
    """The fields with no default are refused at the document, not only at the schema.

    The document does not forbid extra keys — an unknown one is dropped rather than refused — so
    this is the only validation a write bypassing the API is subject to.
    """
    fields = dict(PAYLOAD)
    del fields["company"]

    with pytest.raises(ValidationError):
        Application(**fields)


async def test_rejects_unknown_status(db: AsyncMongoClient[dict[str, Any]]) -> None:
    """The enum is enforced before the value reaches a schemaless database."""
    with pytest.raises(ValidationError):
        Application(**PAYLOAD | {"status": "banana"})


async def test_stores_status_as_plain_string(db: AsyncMongoClient[dict[str, Any]]) -> None:
    """Status persists as its lowercase value, so raw mongosh queries match."""
    await Application(**PAYLOAD | {"status": Status.APPLIED}).insert()

    raw = await Application.get_pymongo_collection().find_one({})

    assert raw is not None
    assert raw["status"] == "applied"


async def test_applied_date_round_trips(db: AsyncMongoClient[dict[str, Any]]) -> None:
    """A date survives the trip through BSON, which has no date type of its own.

    MongoDB stores it as a datetime at midnight and Beanie converts it back on read, so raw
    queries have to use datetimes rather than a date string.
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
    """BSON stores no offset, so this holds only because the client is ``tz_aware``."""
    await Application(**PAYLOAD).insert()

    fetched = await Application.find_one({})

    assert fetched is not None
    assert fetched.created_at.tzinfo is not None
    assert fetched.created_at.utcoffset() == UTC.utcoffset(None)


async def test_the_url_index_is_partial_and_unique(db: AsyncMongoClient[dict[str, Any]]) -> None:
    """The rule is enforced by the database, not only by the endpoint.

    A write reaching MongoDB by any other route — a worker, a shell, a future bot — is subject to
    the same constraint, which an endpoint-level check alone would not provide.
    """
    indexes = {
        index["name"]: index
        async for index in await Application.get_pymongo_collection().list_indexes()
    }

    index = indexes["url_unique_when_present"]
    assert index["unique"] is True
    assert index["partialFilterExpression"] == {"url": {"$gt": ""}}


async def test_id_is_exposed_as_id_not_underscore_id(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """Regression test for a leaked MongoDB key.

    Returning the document directly made the JSON say ``_id`` while the model documented ``id``,
    so a client reading the docstring got undefined.
    """
    saved = await Application(**PAYLOAD).insert()

    item = (await api.get("/api/applications")).json()[0]

    assert "_id" not in item
    assert item["id"] == str(saved.id)


async def test_no_internal_fields_leak(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """Only the declared fields are returned, so Beanie internals stay out of the contract."""
    await Application(**PAYLOAD).insert()

    item = (await api.get("/api/applications")).json()[0]

    assert set(item) == PUBLISHED_FIELDS


async def test_openapi_marks_always_present_fields_required(api: AsyncClient) -> None:
    """Regression test for always-present fields described as optional.

    FastAPI reused the input-shaped document schema for output, so ``id`` was typed nullable and
    ``created_at``, ``status`` and ``notes`` were not required at all. A generated client then
    forced null checks on fields that can never be null.
    """
    schema = (await api.get("/openapi.json")).json()["components"]["schemas"]["ApplicationRead"]

    assert set(schema["required"]) == PUBLISHED_FIELDS
    assert schema["properties"]["id"] == {"type": "string", "title": "Id"}


async def test_applied_date_is_the_only_nullable_field(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """applied_date is null until a job is applied to; nothing else is ever null."""
    await Application(**PAYLOAD).insert()
    await Application(
        **PAYLOAD | {"url": "https://example.com/jobs/2", "status": Status.APPLIED},
        applied_date=None,
    ).insert()

    body = (await api.get("/api/applications")).json()

    for item in body:
        nulls = {key for key, value in item.items() if value is None}
        assert nulls <= {"applied_date"}
