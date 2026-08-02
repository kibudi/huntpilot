"""Tests for the HTTP endpoints."""

import asyncio
from datetime import UTC, datetime
from typing import Any

from httpx import AsyncClient
from pymongo import AsyncMongoClient

from app.models import Application, Status

REQUIRED = {
    "role": "Backend Engineer",
    "location": "Remote (IL)",
    "source": "LinkedIn",
}


async def seed(company: str, **overrides: Any) -> Application:
    """Inserts one application, filling in everything not given."""
    fields: dict[str, Any] = {
        "company": company,
        "url": f"https://example.com/jobs/{company}",
        **REQUIRED,
        **overrides,
    }
    return await Application(**fields).insert()


async def test_health_reports_ok(api: AsyncClient) -> None:
    """The health endpoint answers without touching the database."""
    response = await api.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_list_is_empty_initially(api: AsyncClient) -> None:
    """With nothing stored the endpoint returns an empty list, not an error."""
    response = await api.get("/api/applications")

    assert response.status_code == 200
    assert response.json() == []


async def test_list_returns_stored_applications(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """Stored documents come back with their fields intact."""
    await seed("Gong", status=Status.APPLIED)

    body = (await api.get("/api/applications")).json()

    assert len(body) == 1
    assert body[0]["company"] == "Gong"
    assert body[0]["status"] == "applied"
    assert body[0]["notes"] == ""


async def test_list_is_sorted_by_most_recently_updated(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """The most recently updated application is first.

    A short sleep separates the timestamps; without it the two documents can share a value and the
    order becomes arbitrary.
    """
    await seed("First")
    await asyncio.sleep(0.05)
    await seed("Second")

    body = (await api.get("/api/applications")).json()

    assert [item["company"] for item in body] == ["Second", "First"]


async def test_timestamps_carry_an_offset(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """Served timestamps are unambiguous, so a client cannot read them as local time.

    Regression test: these were previously serialised without an offset, and a consumer in UTC+3
    computed an age three hours too large for a document written seconds earlier.
    """
    await seed("Gong")

    body = (await api.get("/api/applications")).json()
    created_at = datetime.fromisoformat(body[0]["created_at"])

    assert created_at.tzinfo is not None
    assert abs((datetime.now(UTC) - created_at).total_seconds()) < 60


async def test_applied_date_serialises_as_a_date(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """applied_date is a plain date in the JSON, despite BSON storing a midnight datetime."""
    await seed("Gong", status=Status.APPLIED, applied_date=datetime(2026, 7, 15).date())

    body = (await api.get("/api/applications")).json()

    assert body[0]["applied_date"] == "2026-07-15"
