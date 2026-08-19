"""Tests for the endpoint listing postings swept from company boards."""

from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import AsyncClient
from pymongo import AsyncMongoClient

from app.models import ATS, Company, Posting, PostingStatus

EXPECTED_FIELDS = {
    "id",
    "company",
    "ats",
    "title",
    "location",
    "region",
    "url",
    "status",
    "first_seen_at",
    "last_seen_at",
    "closed_at",
}
"""Exactly the fields the contract publishes, so a leaked storage field fails the test."""


async def seed_company(name: str, ats: ATS = ATS.GREENHOUSE, token: str = "acme") -> Company:
    """Puts one company on the watchlist under a display name that differs from its token."""
    return await Company(name=name, ats=ats, token=token).insert()


async def seed(
    external_id: str = "1",
    token: str = "acme",
    ats: ATS = ATS.GREENHOUSE,
    **overrides: Any,
) -> Posting:
    """Inserts one posting, filling in everything not given.

    The identifying triple is passed separately from the rest because the unique index is built on
    it, so tests that store more than one posting have to vary it deliberately.
    """
    fields: dict[str, Any] = {
        "company_token": token,
        "ats": ats,
        "external_id": external_id,
        "url": f"https://boards.example.com/{token}/{external_id}",
        "title": "Backend Engineer",
        "location_raw": "Tel Aviv, Israel",
        **overrides,
    }
    return await Posting(**fields).insert()


async def test_list_is_empty_initially(api: AsyncClient) -> None:
    """With nothing swept the endpoint returns an empty list, not an error."""
    response = await api.get("/api/postings")

    assert response.status_code == 200
    assert response.json() == []


async def test_posting_is_returned_with_its_company_display_name(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """The company is the watchlist entry's name, and the location comes from ``location_raw``."""
    await seed_company("Cato Networks", token="catonetworks")
    await seed(token="catonetworks")

    body = (await api.get("/api/postings")).json()

    assert len(body) == 1
    assert body[0]["company"] == "Cato Networks"
    assert body[0]["ats"] == "greenhouse"
    assert body[0]["title"] == "Backend Engineer"
    assert body[0]["location"] == "Tel Aviv, Israel"
    assert body[0]["status"] == "open"
    assert body[0]["closed_at"] is None


async def test_response_exposes_exactly_the_agreed_fields(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """Sweep bookkeeping stays internal: no ``external_id``, ``company_token`` or ``missed_sweeps``.

    Asserting the whole key set rather than the absence of three names also catches a field added
    to the document later and published without anyone deciding to.
    """
    await seed_company("Cato Networks", token="catonetworks")
    await seed(token="catonetworks", missed_sweeps=1)

    body = (await api.get("/api/postings")).json()

    assert set(body[0]) == EXPECTED_FIELDS


async def test_region_is_derived_from_the_stored_location(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """The backend says which region a posting is in, so no client keeps its own city list.

    Kfar Saba is the case that motivated the field: it is on the backend's list of Israeli
    spellings and was missing from the dashboard's copy, so the posting was stored and then not
    counted. Naming a city here rather than the tidy "Tel Aviv, Israel" is what makes this a
    regression test rather than a restatement of the obvious.
    """
    await seed_company("Cato Networks", token="catonetworks")
    await seed("local", token="catonetworks", location_raw="Kfar Saba")
    await seed("far", token="catonetworks", location_raw="Remote - United States")

    body = (await api.get("/api/postings")).json()

    assert {item["location"]: item["region"] for item in body} == {
        "Kfar Saba": "israel",
        "Remote - United States": "remote",
    }


async def test_sorted_by_newest_discovery_first(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """Order is ``first_seen_at`` descending, not ``last_seen_at``.

    The two are deliberately opposed here: the posting discovered first was confirmed most
    recently, so a sort on the wrong key produces the exactly reversed list.
    """
    await seed_company("Cato Networks", token="catonetworks")
    await seed(
        "old",
        token="catonetworks",
        title="Discovered first",
        first_seen_at=datetime(2026, 1, 1, tzinfo=UTC),
        last_seen_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    await seed(
        "new",
        token="catonetworks",
        title="Discovered second",
        first_seen_at=datetime(2026, 6, 1, tzinfo=UTC),
        last_seen_at=datetime(2026, 6, 2, tzinfo=UTC),
    )

    body = (await api.get("/api/postings")).json()

    assert [item["title"] for item in body] == ["Discovered second", "Discovered first"]


async def test_status_filter_selects_only_matching_postings(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """``status=open`` and ``status=closed`` each return only their own postings."""
    await seed_company("Cato Networks", token="catonetworks")
    await seed("live", token="catonetworks", title="Still listed")
    await seed(
        "gone",
        token="catonetworks",
        title="Taken down",
        status=PostingStatus.CLOSED,
        closed_at=datetime(2026, 7, 1, tzinfo=UTC),
    )

    open_body = (await api.get("/api/postings", params={"status": "open"})).json()
    closed_body = (await api.get("/api/postings", params={"status": "closed"})).json()

    assert [item["title"] for item in open_body] == ["Still listed"]
    assert [item["title"] for item in closed_body] == ["Taken down"]
    assert closed_body[0]["closed_at"] is not None


async def test_omitting_status_returns_open_and_closed(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """No filter means both states, since a closed posting is a result and not noise."""
    await seed_company("Cato Networks", token="catonetworks")
    await seed("live", token="catonetworks")
    await seed("gone", token="catonetworks", status=PostingStatus.CLOSED)

    body = (await api.get("/api/postings")).json()

    assert {item["status"] for item in body} == {"open", "closed"}


async def test_unknown_status_is_rejected(api: AsyncClient) -> None:
    """A status outside the enum is a 422 rather than a silently unfiltered list."""
    response = await api.get("/api/postings", params={"status": "archived"})

    assert response.status_code == 422


async def test_posting_survives_its_company_leaving_the_watchlist(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """A posting with no watchlist entry is still listed, labelled with its token.

    Removing a company stops its board being swept but leaves everything already recorded, so this
    is a state the endpoint must serve rather than an inconsistency it can refuse.
    """
    await seed(token="catonetworks")

    response = await api.get("/api/postings")
    body = response.json()

    assert response.status_code == 200
    assert len(body) == 1
    assert body[0]["company"] == "catonetworks"


async def test_display_name_is_matched_on_ats_as_well_as_token(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """Two boards sharing a token are separate companies, and must not borrow each other's name.

    Both are asserted rather than just one. Keying the names on the token alone leaves whichever
    company was read last holding the key, so a single-posting check passes half the time by
    accident; requiring the two postings to disagree fails whichever one wins.
    """
    await seed_company("Acme Security", ats=ATS.GREENHOUSE, token="acme")
    await seed_company("Acme Robotics", ats=ATS.LEVER, token="acme")
    await seed(ats=ATS.GREENHOUSE, token="acme", title="On Greenhouse")
    await seed(ats=ATS.LEVER, token="acme", title="On Lever")

    body = (await api.get("/api/postings")).json()

    assert {item["title"]: item["company"] for item in body} == {
        "On Greenhouse": "Acme Security",
        "On Lever": "Acme Robotics",
    }


async def test_company_names_are_not_looked_up_one_posting_at_a_time(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Names come from one watchlist read matched in Python, never a query per row.

    Guarded by making the single-document lookup unusable rather than by timing anything: a
    per-row implementation reaches for ``Company.find_one`` inside the loop and hits this, while
    the batched one never calls it. Timing would only say the endpoint was slow, and on five
    postings it would not even say that.
    """

    def refuse(*args: Any, **kwargs: Any) -> None:
        """Stands in for the per-posting lookup so that using it fails the test."""
        raise AssertionError("company names must not be fetched one posting at a time")

    await seed_company("Cato Networks", token="catonetworks")
    for index in range(5):
        await seed(str(index), token="catonetworks")
    monkeypatch.setattr(Company, "find_one", refuse)

    body = (await api.get("/api/postings")).json()

    assert [item["company"] for item in body] == ["Cato Networks"] * 5
