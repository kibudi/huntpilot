"""Tests for reading and replacing the stored search profile over the API.

``test_profile.py`` covers the model and the file it is loaded from. This covers what changes once
the profile lives in the database: that an empty database still has one, that an edit sticks, and
that the rules the file has always been held to are the rules an edit is held to as well.

The refusals are the point. Every one of them — a score written as a percentage, a pattern with an
unclosed bracket, an emptied whitelist — produces a sweep that stores nothing and reports no error,
so an edit that makes one of them has to come back as a rejection naming the thing that is wrong.
Saved and silently filtering everything away is the failure this endpoint exists to prevent.
"""

from typing import Any

from httpx import AsyncClient
from pymongo import AsyncMongoClient

from app.models import ATS, Company, Posting, SearchProfile
from app.profile import default_profile

COMMITTED: dict[str, Any] = default_profile.model_dump(mode="json")
"""The committed profile in wire form, which every test here sends back with one thing changed.

Taken from the loaded default rather than written out again, so a field added to ``Profile`` does
not leave these tests posting a body that is missing it and failing for a reason none of them is
about.
"""


def _body(**overrides: Any) -> dict[str, Any]:
    """Builds a request body from the committed profile with the given fields replaced."""
    return COMMITTED | overrides


async def test_an_unseeded_database_still_has_a_profile(api: AsyncClient) -> None:
    """A database nothing has written to answers with the committed profile, not a 404.

    The dashboard's editor is filled from this endpoint, so a profile that did not exist until
    something had saved one would leave no way to save the first one.
    """
    response = await api.get("/api/profile")

    assert response.status_code == 200
    assert response.json() == COMMITTED


async def test_the_profile_is_seeded_once_and_not_on_every_read(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """Reading twice must not leave two profiles behind.

    Two stored profiles would make "the stored profile" mean whichever the driver reached first,
    while an edit changed the other — a split that no later read would reveal.
    """
    await api.get("/api/profile")
    await api.get("/api/profile")

    assert await SearchProfile.find_all().count() == 1


async def test_an_edit_is_what_the_next_read_returns(api: AsyncClient) -> None:
    """The stored profile is the source of truth: seeding must not overwrite an edit."""
    await api.put("/api/profile", json=_body(max_years=9))

    assert (await api.get("/api/profile")).json()["max_years"] == 9


async def test_what_a_read_returns_can_be_sent_straight_back(api: AsyncClient) -> None:
    """The two directions are one shape, which is what makes an editor filled from ``GET`` work.

    A field present on the way out and rejected on the way in would break the only workflow this
    endpoint has: load the profile, change one thing, save it.
    """
    loaded = (await api.get("/api/profile")).json()

    response = await api.put("/api/profile", json=loaded)

    assert response.status_code == 200
    assert response.json() == loaded


async def test_the_stored_profile_is_the_normalised_one(api: AsyncClient) -> None:
    """What comes back is what the filters will use, not an echo of what was sent.

    Location fragments are matched against lower-cased text, so a capitalised one would match
    nothing and quietly discard every posting in that city — the file is forgiving about this and
    an edit has to be too. An omitted ``unknown`` comes back as the empty object it will be treated
    as, rather than as an absence the client has to guess the meaning of.
    """
    sent = _body(local_fragments=["Tel Aviv", "HAIFA"])
    del sent["unknown"]

    stored = (await api.put("/api/profile", json=sent)).json()

    assert stored["local_fragments"] == ["tel aviv", "haifa"]
    assert stored["unknown"] == {}
    assert (await api.get("/api/profile")).json() == stored


async def test_a_score_written_as_a_percentage_is_refused(api: AsyncClient) -> None:
    """The obvious mistake, and the one that keeps nothing at all.

    The stored profile is checked afterwards as well: a rejection that had already written is worse
    than no rejection, because the reply says the edit failed while the sweep uses it.
    """
    response = await api.put("/api/profile", json=_body(min_tech_score=80))

    assert response.status_code == 422
    assert "min_tech_score" in response.text
    assert (await api.get("/api/profile")).json()["min_tech_score"] == 0.8


async def test_a_broken_pattern_is_refused_naming_the_entry(api: AsyncClient) -> None:
    """An unclosed bracket is a plausible typo, and a profile holds sixty patterns to find it in.

    Compiled as the profile is validated rather than at first use, so it is caught here instead of
    raising in the middle of a sweep, inside the one ``except`` that reads any exception as a board
    that could not be read — where one typo would be reported as several dozen companies being down.
    """
    response = await api.put(
        "/api/profile", json=_body(known=COMMITTED["known"] | {"sql": "[unclosed"})
    )

    assert response.status_code == 422
    assert "sql" in response.text
    assert "valid regular expression" in response.text


async def test_a_whitelist_emptied_by_an_edit_is_refused(api: AsyncClient) -> None:
    """Either empty whitelist matches nothing ever written: a filter that hides its own bug."""
    overrides: tuple[dict[str, Any], ...] = ({"role_families": {}}, {"known": {}})
    for override in overrides:
        response = await api.put("/api/profile", json=_body(**override))

        assert response.status_code == 422, override


async def test_a_profile_naming_nowhere_is_refused(api: AsyncClient) -> None:
    """With no location in scope every posting fails the first gate and the sweep looks calm."""
    response = await api.put(
        "/api/profile", json=_body(local_fragments=[], remote_fragments=[])
    )

    assert response.status_code == 422
    assert "must name somewhere" in response.text


async def test_a_misspelt_field_is_refused(api: AsyncClient) -> None:
    """The quietest failure of all: the real field keeps its default and nothing says so."""
    response = await api.put("/api/profile", json=_body(min_tech_scores=0.6))

    assert response.status_code == 422
    assert "min_tech_scores" in response.text


async def test_postings_are_classified_with_the_stored_profile(
    api: AsyncClient, db: AsyncMongoClient[dict[str, Any]]
) -> None:
    """Editing the profile reclassifies postings already swept, with no sweep and no restart.

    ``region`` is derived on the way out from the profile's list of local spellings, so the list
    the endpoint reads has to be the stored one rather than the file loaded at import. Kfar Saba is
    the city that motivated the field, and dropping it from the profile is what proves the endpoint
    is reading the edit.
    """
    await Company(name="Cato Networks", ats=ATS.GREENHOUSE, token="cato").insert()
    await Posting(
        company_token="cato",
        ats=ATS.GREENHOUSE,
        external_id="1",
        url="https://boards.example.com/cato/1",
        title="Backend Engineer",
        location_raw="Kfar Saba",
    ).insert()

    assert (await api.get("/api/postings")).json()[0]["region"] == "israel"

    await api.put("/api/profile", json=_body(local_fragments=["tel aviv"]))

    assert (await api.get("/api/postings")).json()[0]["region"] == "remote"
