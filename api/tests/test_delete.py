"""Tests for removing an application over HTTP."""

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


async def test_removes_the_application(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """A deleted application is gone from a later read."""
    created = await create(api)

    response = await api.delete(f"/api/applications/{created['id']}")

    assert response.status_code == HTTPStatus.NO_CONTENT
    assert (await api.get("/api/applications")).json() == []


async def test_returns_no_body(api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]) -> None:
    """204 forbids a body, so nothing is echoed back."""
    created = await create(api)

    response = await api.delete(f"/api/applications/{created['id']}")

    assert response.content == b""


async def test_leaves_other_applications_alone(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """Only the identified document is removed.

    This is what separates a targeted delete from one whose filter matched everything, which a
    single-document test cannot tell apart.
    """
    doomed = await create(api, url="https://example.com/jobs/1")
    kept = await create(api, url="https://example.com/jobs/2")

    await api.delete(f"/api/applications/{doomed['id']}")

    remaining = (await api.get("/api/applications")).json()
    assert [application["id"] for application in remaining] == [kept["id"]]


async def test_repeat_delete_is_not_found(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """Deleting the same application twice reports the second attempt as a miss.

    Reporting 204 again would hide a wrong identifier on the one endpoint whose mistakes cannot
    be undone.
    """
    created = await create(api)

    first = await api.delete(f"/api/applications/{created['id']}")
    second = await api.delete(f"/api/applications/{created['id']}")

    assert first.status_code == HTTPStatus.NO_CONTENT
    assert second.status_code == HTTPStatus.NOT_FOUND


async def test_unknown_id_is_not_found(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """A well-formed identifier that matches nothing is a 404."""
    response = await api.delete(f"/api/applications/{MISSING_ID}")

    assert response.status_code == HTTPStatus.NOT_FOUND


async def test_malformed_id_is_rejected(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """An identifier that is not an ObjectId fails validation rather than erroring."""
    response = await api.delete("/api/applications/banana")

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
