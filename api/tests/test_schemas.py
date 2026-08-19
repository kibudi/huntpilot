"""Tests for the shape of the API's responses and its OpenAPI description."""

from typing import Any

from conftest import PAYLOAD
from httpx import AsyncClient
from pymongo import AsyncMongoClient

from app.models import Application, Status


async def test_id_is_exposed_as_id_not_underscore_id(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """The identifier is `id`, matching the attribute name clients read about.

    Regression test: returning the document directly leaked MongoDB's own key, so the JSON said
    `_id` while the model documented `id`, and a client reading the docstring got undefined.
    """
    saved = await Application(**PAYLOAD).insert()

    item = (await api.get("/api/applications")).json()[0]

    assert "_id" not in item
    assert item["id"] == str(saved.id)


async def test_id_is_a_string(api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]) -> None:
    """The identifier serialises as a string, since JSON has no ObjectId type."""
    await Application(**PAYLOAD).insert()

    item = (await api.get("/api/applications")).json()[0]

    assert isinstance(item["id"], str)


async def test_no_internal_fields_leak(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """Only the declared fields are returned, so Beanie internals stay out of the contract."""
    await Application(**PAYLOAD).insert()

    item = (await api.get("/api/applications")).json()[0]

    assert set(item) == {
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


async def test_openapi_marks_always_present_fields_required(api: AsyncClient) -> None:
    """The schema says a field is optional only when it genuinely can be absent.

    Regression test: FastAPI reused the input-shaped document schema for output, so `id` was typed
    nullable and `created_at`, `status` and `notes` were not required at all. A generated client
    then forced null checks on fields that are always present.
    """
    schema = (await api.get("/openapi.json")).json()["components"]["schemas"]["ApplicationRead"]

    assert set(schema["required"]) == {
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
