"""Tests for the uniqueness rule on ``url``."""

from http import HTTPStatus
from typing import Any

from conftest import PAYLOAD
from httpx import AsyncClient, Response
from pymongo import AsyncMongoClient

from app.models import Application


async def post_application(api: AsyncClient, **overrides: Any) -> Response:
    """Posts one application and returns the raw response.

    Kept here rather than taken from ``conftest`` because these tests assert on status codes: a
    duplicate never produces a body worth reading, and a helper that parsed one would have nothing
    to hand back.
    """
    return await api.post("/api/applications", json=PAYLOAD | overrides)


async def test_rejects_a_second_application_with_the_same_url(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """The same posting link cannot be tracked twice."""
    first = await post_application(api)
    second = await post_application(api, company="Someone Else")

    assert first.status_code == HTTPStatus.CREATED
    assert second.status_code == HTTPStatus.CONFLICT


async def test_blank_urls_do_not_collide(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """Any number of applications may have no posting link.

    Agency roles and undisclosed employers genuinely have none, and they are stored as ``""``
    rather than absent. A plain unique index would read every blank as a duplicate of the others
    and refuse to build, which would stop the application from starting at all.
    """
    responses = [await post_application(api, company=f"Agency {n}", url="") for n in range(4)]

    assert [response.status_code for response in responses] == [HTTPStatus.CREATED] * 4
    assert len((await api.get("/api/applications")).json()) == 4


async def test_different_urls_are_both_accepted(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """Distinct posting links are unaffected by the rule."""
    first = await post_application(api, url="https://example.com/jobs/1")
    second = await post_application(api, url="https://example.com/jobs/2")

    assert first.status_code == HTTPStatus.CREATED
    assert second.status_code == HTTPStatus.CREATED


async def test_a_rejected_duplicate_is_not_stored(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """A 409 leaves the collection as it was, rather than half-writing the document."""
    await post_application(api)
    await post_application(api, company="Someone Else")

    listed = (await api.get("/api/applications")).json()
    assert len(listed) == 1
    assert listed[0]["company"] == "Gong"


async def test_patch_cannot_move_a_url_onto_another_application(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """The rule cannot be circumvented by creating with one link and patching to another."""
    await post_application(api, url="https://example.com/jobs/1")
    second = (await post_application(api, url="https://example.com/jobs/2")).json()

    response = await api.patch(
        f"/api/applications/{second['id']}", json={"url": "https://example.com/jobs/1"}
    )

    assert response.status_code == HTTPStatus.CONFLICT


async def test_patch_may_rewrite_an_application_to_its_own_url(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """Sending a document its existing link is not a collision with itself."""
    created = (await post_application(api)).json()

    response = await api.patch(
        f"/api/applications/{created['id']}", json={"url": PAYLOAD["url"]}
    )

    assert response.status_code == HTTPStatus.OK


async def test_the_index_is_partial_and_unique(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
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
