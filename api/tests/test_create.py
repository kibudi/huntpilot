"""Tests for creating applications over HTTP."""

from datetime import UTC, datetime
from http import HTTPStatus
from typing import Any

from httpx import AsyncClient
from pymongo import AsyncMongoClient

from app.models import Application

PAYLOAD = {
    "company": "Gong",
    "role": "Backend Engineer",
    "location": "Remote (IL)",
    "source": "LinkedIn",
    "url": "https://example.com/jobs/1",
}


async def test_creates_and_returns_the_stored_application(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """A valid payload is stored and echoed back with the server's own fields filled in."""
    response = await api.post("/api/applications", json=PAYLOAD)

    assert response.status_code == HTTPStatus.CREATED
    body = response.json()
    assert body["company"] == "Gong"
    assert body["id"]
    assert body["status"] == "saved"
    assert body["notes"] == ""
    assert body["applied_date"] is None
    assert datetime.fromisoformat(body["created_at"]).tzinfo is not None


async def test_created_application_is_persisted(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """What was created comes back from the list endpoint."""
    created = (await api.post("/api/applications", json=PAYLOAD)).json()

    listed = (await api.get("/api/applications")).json()

    assert [item["id"] for item in listed] == [created["id"]]


async def test_rejects_server_owned_fields(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """A client cannot choose the identifier or the timestamps.

    Without ``extra="forbid"`` these would be silently dropped, so a caller setting created_at
    would believe it had taken effect.
    """
    for field, value in (
        ("id", "6a6f000000000000000000000"),
        ("created_at", datetime.now(UTC).isoformat()),
        ("updated_at", datetime.now(UTC).isoformat()),
    ):
        response = await api.post("/api/applications", json=PAYLOAD | {field: value})

        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, field

    assert await Application.find_all().count() == 0


async def test_rejects_unknown_field(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """An unrecognised key is refused rather than stored as one nothing queries.

    Every required field is present, so the rejection can only come from ``extra="forbid"``.
    Removing a required field as well would make this pass for the wrong reason.
    """
    response = await api.post("/api/applications", json=PAYLOAD | {"comapny": "Gong"})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert response.json()["detail"][0]["type"] == "extra_forbidden"
    assert response.json()["detail"][0]["loc"] == ["body", "comapny"]


async def test_rejects_missing_required_field(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """The fields with no default must be supplied."""
    payload = dict(PAYLOAD)
    del payload["company"]

    response = await api.post("/api/applications", json=payload)

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert response.json()["detail"][0]["loc"] == ["body", "company"]


async def test_rejects_unknown_status(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """Status must be one of the pipeline values."""
    response = await api.post("/api/applications", json=PAYLOAD | {"status": "banana"})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


async def test_response_body_matches_the_list_shape(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """The created body is usable without re-fetching, so it must match what the list returns."""
    created = (await api.post("/api/applications", json=PAYLOAD)).json()

    listed = (await api.get("/api/applications")).json()[0]

    assert created == listed


async def test_new_document_has_equal_timestamps(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """A never-modified document reports the same created_at and updated_at.

    Regression test: the two fields were set by separate default calls and the body was serialised
    from memory at microsecond precision, while MongoDB stores milliseconds. The POST body then
    disagreed with every later read of the same record.
    """
    created = (await api.post("/api/applications", json=PAYLOAD)).json()

    assert created["created_at"] == created["updated_at"]

    listed = (await api.get("/api/applications")).json()[0]

    assert listed["created_at"] == created["created_at"]
    assert listed["updated_at"] == created["updated_at"]


async def test_accepts_optional_fields(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """Status, applied_date and notes may be supplied rather than defaulted."""
    response = await api.post(
        "/api/applications",
        json=PAYLOAD | {"status": "applied", "applied_date": "2026-07-15", "notes": "referred"},
    )

    body = response.json()
    assert body["status"] == "applied"
    assert body["applied_date"] == "2026-07-15"
    assert body["notes"] == "referred"
