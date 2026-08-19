"""Tests for the application endpoints, in the order a client meets them.

Listing first, then create, update and delete, and last the uniqueness rule on ``url``, which is
the one behaviour that spans two endpoints.
"""

import asyncio
from datetime import UTC, date, datetime
from http import HTTPStatus
from typing import Any

from conftest import PAYLOAD, create
from httpx import AsyncClient
from pymongo import AsyncMongoClient

from app.models import Application, Status

MISSING_ID = "6a6f000000000000000000ff"
"""A well-formed ObjectId that no document has, for separating a miss from a malformed id."""


async def seed(company: str, **overrides: Any) -> Application:
    """Inserts one application directly, without going through the API.

    The listing tests use this so that what they assert about reading is not also a claim about
    the create endpoint. The url is derived from the company so two seeded documents never collide
    on the uniqueness rule.

    Args:
        company: The company name, which also distinguishes the url.
        **overrides: Fields to change on ``PAYLOAD`` before inserting.

    Returns:
        The inserted document.
    """
    fields = PAYLOAD | {"company": company, "url": f"https://example.com/jobs/{company}"}
    return await Application(**fields | overrides).insert()


async def test_health_reports_ok(api: AsyncClient) -> None:
    """The health endpoint answers without touching the database."""
    response = await api.get("/health")

    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"status": "ok"}


async def test_list_is_empty_initially(api: AsyncClient) -> None:
    """An empty collection is an empty list, not an error."""
    response = await api.get("/api/applications")

    assert response.status_code == HTTPStatus.OK
    assert response.json() == []


async def test_list_returns_stored_applications(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """Documents written outside the API list correctly, so reading does not lean on create."""
    await seed("Gong", status=Status.APPLIED)

    body = (await api.get("/api/applications")).json()

    assert len(body) == 1
    assert body[0]["company"] == "Gong"
    assert body[0]["status"] == "applied"
    assert body[0]["notes"] == ""


async def test_list_is_sorted_by_most_recently_updated(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """A short sleep separates the timestamps; sharing one would make the order arbitrary."""
    await seed("First")
    await asyncio.sleep(0.05)
    await seed("Second")

    body = (await api.get("/api/applications")).json()

    assert [item["company"] for item in body] == ["Second", "First"]


async def test_list_timestamps_carry_an_offset(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """Regression test for timestamps served without an offset.

    A consumer in UTC+3 read them as local time and computed an age three hours too large for a
    document written seconds earlier.
    """
    await seed("Gong")

    body = (await api.get("/api/applications")).json()
    created_at = datetime.fromisoformat(body[0]["created_at"])

    assert created_at.tzinfo is not None
    assert abs((datetime.now(UTC) - created_at).total_seconds()) < 60


async def test_list_serialises_applied_date_as_a_date(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """BSON stores a midnight datetime, so the plain date in the JSON is a conversion."""
    await seed("Gong", status=Status.APPLIED, applied_date=date(2026, 7, 15))

    body = (await api.get("/api/applications")).json()

    assert body[0]["applied_date"] == "2026-07-15"


async def test_create_stores_and_returns_the_application(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """A valid payload comes back with the server's own fields filled in."""
    response = await api.post("/api/applications", json=PAYLOAD)

    assert response.status_code == HTTPStatus.CREATED
    body = response.json()
    assert body["company"] == "Gong"
    assert body["id"]
    assert body["status"] == "saved"
    assert body["notes"] == ""
    assert body["applied_date"] is None
    assert datetime.fromisoformat(body["created_at"]).tzinfo is not None


async def test_create_returns_the_same_body_the_list_returns(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """The created body is usable without re-fetching, which also proves it was stored."""
    created = (await api.post("/api/applications", json=PAYLOAD)).json()

    listed = (await api.get("/api/applications")).json()[0]

    assert created == listed


async def test_create_returns_equal_timestamps(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """Regression test for a POST body that disagreed with every later read.

    The two fields were set by separate default calls, and the body was serialised from memory at
    microsecond precision while MongoDB stores milliseconds.
    """
    created = (await api.post("/api/applications", json=PAYLOAD)).json()

    assert created["created_at"] == created["updated_at"]

    listed = (await api.get("/api/applications")).json()[0]

    assert listed["created_at"] == created["created_at"]
    assert listed["updated_at"] == created["updated_at"]


async def test_create_accepts_the_optional_fields(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """The fields with defaults may be supplied rather than defaulted."""
    response = await api.post(
        "/api/applications",
        json=PAYLOAD | {"status": "applied", "applied_date": "2026-07-15", "notes": "referred"},
    )

    body = response.json()
    assert body["status"] == "applied"
    assert body["applied_date"] == "2026-07-15"
    assert body["notes"] == "referred"


async def test_create_rejects_a_missing_required_field(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """The fields with no default must be supplied."""
    payload = dict(PAYLOAD)
    del payload["company"]

    response = await api.post("/api/applications", json=payload)

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert response.json()["detail"][0]["loc"] == ["body", "company"]


async def test_create_rejects_an_unknown_field(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """Every required field is present, so the rejection can only come from ``extra="forbid"``.

    This is the only layer that catches a typo: the document itself ignores an unknown key, so a
    misspelled field arriving here would otherwise be dropped and every query on the real name
    would miss it.
    """
    response = await api.post("/api/applications", json=PAYLOAD | {"comapny": "Gong"})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert response.json()["detail"][0]["type"] == "extra_forbidden"
    assert response.json()["detail"][0]["loc"] == ["body", "comapny"]


async def test_create_rejects_an_unknown_status(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """Status must be one of the pipeline values."""
    response = await api.post("/api/applications", json=PAYLOAD | {"status": "banana"})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


async def test_create_rejects_server_owned_fields(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """Without ``extra="forbid"`` a caller setting created_at would believe it had taken effect."""
    for field, value in (
        ("id", "6a6f000000000000000000000"),
        ("created_at", datetime.now(UTC).isoformat()),
        ("updated_at", datetime.now(UTC).isoformat()),
    ):
        response = await api.post("/api/applications", json=PAYLOAD | {field: value})

        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, field

    assert await Application.find_all().count() == 0


async def test_update_changes_only_the_given_field(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """This is what makes it a PATCH rather than a replacement."""
    created = await create(api)

    body = (
        await api.patch(f"/api/applications/{created['id']}", json={"status": "interview"})
    ).json()

    assert body["status"] == "interview"
    assert body["company"] == created["company"]
    assert body["notes"] == created["notes"]
    assert body["id"] == created["id"]


async def test_update_is_persisted(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """The response matches what a later read returns."""
    created = await create(api)

    patched = (
        await api.patch(f"/api/applications/{created['id']}", json={"status": "offer"})
    ).json()
    listed = (await api.get("/api/applications")).json()[0]

    assert patched == listed


async def test_update_bumps_updated_at_but_not_created_at(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """MongoDB has no on-update mechanism, so this holds only because the endpoint sets it.

    Without it the dashboard's sort order and the bot's staleness checks would both be wrong.
    """
    created = await create(api)
    await asyncio.sleep(0.05)

    body = (await api.patch(f"/api/applications/{created['id']}", json={"notes": "replied"})).json()

    assert body["created_at"] == created["created_at"]
    assert body["updated_at"] > created["updated_at"]


async def test_update_with_an_empty_body_changes_nothing(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """updated_at included: nothing moved, so bumping it would be a lie the dashboard sorts on."""
    created = await create(api)
    await asyncio.sleep(0.05)

    body = (await api.patch(f"/api/applications/{created['id']}", json={})).json()

    assert body == created


async def test_update_can_clear_applied_date(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """The one nullable field, so a date entered by mistake can be undone."""
    created = await create(api, status="applied", applied_date="2026-07-15")
    assert created["applied_date"] == "2026-07-15"

    body = (
        await api.patch(f"/api/applications/{created['id']}", json={"applied_date": None})
    ).json()

    assert body["applied_date"] is None


async def test_update_rejects_null_on_non_nullable_fields(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """An omitted field and one explicitly sent as null both look like None on the model.

    This only works because the schema inspects which fields were actually supplied.
    """
    created = await create(api)

    for field in ("company", "role", "location", "source", "url", "status", "notes"):
        response = await api.patch(f"/api/applications/{created['id']}", json={field: None})

        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, field


async def test_update_rejects_an_unknown_field(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """A typo must not be silently ignored on the write path either."""
    created = await create(api)

    response = await api.patch(f"/api/applications/{created['id']}", json={"stat": "offer"})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert response.json()["detail"][0]["type"] == "extra_forbidden"


async def test_update_rejects_an_unknown_status(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """Status must remain one of the pipeline values."""
    created = await create(api)

    response = await api.patch(f"/api/applications/{created['id']}", json={"status": "banana"})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


async def test_update_rejects_server_owned_fields(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """The identifier and the timestamps stay the server's on the write path too."""
    created = await create(api)

    for field in ("id", "created_at", "updated_at"):
        response = await api.patch(
            f"/api/applications/{created['id']}", json={field: created.get(field, "x")}
        )

        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, field


async def test_update_of_an_unknown_id_is_not_found(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """A well-formed identifier matching nothing is a miss, not a silent no-op."""
    response = await api.patch(f"/api/applications/{MISSING_ID}", json={"status": "offer"})

    assert response.status_code == HTTPStatus.NOT_FOUND


async def test_update_of_a_malformed_id_is_rejected(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """An identifier that is not an ObjectId fails validation rather than erroring in the driver."""
    response = await api.patch("/api/applications/banana", json={"status": "offer"})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


async def test_delete_removes_the_application(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """The 204 is backed by an actual removal, not only a status code."""
    created = await create(api)

    response = await api.delete(f"/api/applications/{created['id']}")

    assert response.status_code == HTTPStatus.NO_CONTENT
    assert (await api.get("/api/applications")).json() == []


async def test_delete_leaves_other_applications_alone(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """This is what separates a targeted delete from one whose filter matched everything."""
    doomed = await create(api, url="https://example.com/jobs/1")
    kept = await create(api, url="https://example.com/jobs/2")

    await api.delete(f"/api/applications/{doomed['id']}")

    remaining = (await api.get("/api/applications")).json()
    assert [application["id"] for application in remaining] == [kept["id"]]


async def test_delete_twice_is_not_found(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """Reporting 204 again would hide a wrong identifier on the one irreversible endpoint."""
    created = await create(api)

    first = await api.delete(f"/api/applications/{created['id']}")
    second = await api.delete(f"/api/applications/{created['id']}")

    assert first.status_code == HTTPStatus.NO_CONTENT
    assert second.status_code == HTTPStatus.NOT_FOUND


async def test_delete_of_a_malformed_id_is_rejected(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """Validation refuses the identifier before anything is removed."""
    response = await api.delete("/api/applications/banana")

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


async def test_duplicate_url_is_rejected_on_create(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """A posting link identifies a job, so two documents sharing one are one job recorded twice."""
    first = await api.post("/api/applications", json=PAYLOAD)
    second = await api.post("/api/applications", json=PAYLOAD | {"company": "Someone Else"})

    assert first.status_code == HTTPStatus.CREATED
    assert second.status_code == HTTPStatus.CONFLICT


async def test_a_rejected_duplicate_is_not_stored(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """A 409 leaves the collection as it was, rather than half-writing the document."""
    await api.post("/api/applications", json=PAYLOAD)
    await api.post("/api/applications", json=PAYLOAD | {"company": "Someone Else"})

    listed = (await api.get("/api/applications")).json()
    assert len(listed) == 1
    assert listed[0]["company"] == "Gong"


async def test_blank_urls_do_not_collide(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """Agency roles and undisclosed employers genuinely have no link, and are stored as ``""``.

    A plain unique index would read every one of those blanks as a duplicate of the others and
    refuse to build, which would stop the application from starting at all.
    """
    responses = [
        await api.post("/api/applications", json=PAYLOAD | {"company": f"Agency {n}", "url": ""})
        for n in range(4)
    ]

    assert [response.status_code for response in responses] == [HTTPStatus.CREATED] * 4
    assert len((await api.get("/api/applications")).json()) == 4


async def test_duplicate_url_is_rejected_on_update(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """The rule cannot be circumvented by creating with one link and patching to another."""
    await create(api, url="https://example.com/jobs/1")
    second = await create(api, url="https://example.com/jobs/2")

    response = await api.patch(
        f"/api/applications/{second['id']}", json={"url": "https://example.com/jobs/1"}
    )

    assert response.status_code == HTTPStatus.CONFLICT


async def test_a_url_may_be_rewritten_to_itself(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """Sending a document its existing link is not a collision with itself."""
    created = await create(api)

    response = await api.patch(f"/api/applications/{created['id']}", json={"url": PAYLOAD["url"]})

    assert response.status_code == HTTPStatus.OK
