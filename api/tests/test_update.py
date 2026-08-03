"""Tests for changing an existing application over HTTP."""

import asyncio
from http import HTTPStatus
from typing import Any

from httpx import AsyncClient
from pymongo import AsyncMongoClient

PAYLOAD = {
    "company": "Gong",
    "role": "Backend Engineer",
    "location": "Remote (IL)",
    "source": "LinkedIn",
    "url": "https://example.com/jobs/1",
}

MISSING_ID = "6a6f000000000000000000ff"


async def create(api: AsyncClient, **overrides: Any) -> dict[str, Any]:
    """Creates one application and returns the response body."""
    response = await api.post("/api/applications", json=PAYLOAD | overrides)
    body: dict[str, Any] = response.json()
    return body


async def test_changes_only_the_given_field(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """A field left out of the body keeps its value."""
    created = await create(api)

    body = (
        await api.patch(f"/api/applications/{created['id']}", json={"status": "interview"})
    ).json()

    assert body["status"] == "interview"
    assert body["company"] == created["company"]
    assert body["notes"] == created["notes"]
    assert body["id"] == created["id"]


async def test_bumps_updated_at_but_not_created_at(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """A change moves updated_at forward and leaves created_at alone.

    MongoDB has no on-update mechanism, so this only holds because the endpoint sets it. Without
    it the dashboard's sort order and the bot's staleness checks would both be wrong.
    """
    created = await create(api)
    await asyncio.sleep(0.05)

    body = (await api.patch(f"/api/applications/{created['id']}", json={"notes": "replied"})).json()

    assert body["created_at"] == created["created_at"]
    assert body["updated_at"] > created["updated_at"]


async def test_change_is_persisted(api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]) -> None:
    """The response matches what a later read returns."""
    created = await create(api)

    patched = (
        await api.patch(f"/api/applications/{created['id']}", json={"status": "offer"})
    ).json()
    listed = (await api.get("/api/applications")).json()[0]

    assert patched == listed


async def test_empty_body_changes_nothing(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """Sending no fields leaves the document untouched, including updated_at."""
    created = await create(api)
    await asyncio.sleep(0.05)

    body = (await api.patch(f"/api/applications/{created['id']}", json={})).json()

    assert body == created


async def test_unknown_id_is_not_found(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """A well-formed identifier that matches nothing is a 404."""
    response = await api.patch(f"/api/applications/{MISSING_ID}", json={"status": "offer"})

    assert response.status_code == HTTPStatus.NOT_FOUND


async def test_malformed_id_is_rejected(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """An identifier that is not an ObjectId fails validation rather than erroring."""
    response = await api.patch("/api/applications/banana", json={"status": "offer"})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


async def test_rejects_unknown_field(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """An unrecognised key is refused rather than silently ignored."""
    created = await create(api)

    response = await api.patch(f"/api/applications/{created['id']}", json={"stat": "offer"})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert response.json()["detail"][0]["type"] == "extra_forbidden"


async def test_rejects_server_owned_fields(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """A client cannot rewrite the identifier or the timestamps."""
    created = await create(api)

    for field in ("id", "created_at", "updated_at"):
        response = await api.patch(
            f"/api/applications/{created['id']}", json={field: created.get(field, "x")}
        )

        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, field


async def test_rejects_unknown_status(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """Status must remain one of the pipeline values."""
    created = await create(api)

    response = await api.patch(f"/api/applications/{created['id']}", json={"status": "banana"})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


async def test_applied_date_can_be_cleared(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """applied_date may be set to null, to undo a date entered by mistake."""
    created = await create(api, status="applied", applied_date="2026-07-15")
    assert created["applied_date"] == "2026-07-15"

    body = (
        await api.patch(f"/api/applications/{created['id']}", json={"applied_date": None})
    ).json()

    assert body["applied_date"] is None


async def test_rejects_null_on_non_nullable_fields(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """Null is refused for fields the document cannot store as null.

    An omitted field and one explicitly sent as null both look like None on the model, so this
    only works because the schema inspects which fields were actually supplied.
    """
    created = await create(api)

    for field in ("company", "role", "location", "source", "url", "status", "notes"):
        response = await api.patch(f"/api/applications/{created['id']}", json={field: None})

        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, field
