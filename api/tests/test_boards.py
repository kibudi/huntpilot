"""Tests for normalising board payloads and reconciling them against stored postings."""

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from pymongo import AsyncMongoClient

from app.boards import (
    BOARD_URLS,
    MISSES_BEFORE_CLOSED,
    BoardMatch,
    BoardPosting,
    candidate_tokens,
    fetch_board,
    normalise,
    reconcile,
    resolve,
    watch,
)
from app.models import ATS, Company, Posting, PostingStatus

GREENHOUSE_PAYLOAD = {
    "jobs": [
        {
            "id": 5101378008,
            "title": "Backend Engineer",
            "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/5101378008",
            "location": {"name": "Tel Aviv, Israel"},
        }
    ]
}

LEVER_PAYLOAD = [
    {
        "id": "0808b2c0-80f7-478b-9067-812416ac0634",
        "text": "Backend Engineer",
        "hostedUrl": "https://jobs.lever.co/acme/0808b2c0-80f7-478b-9067-812416ac0634",
        "categories": {"location": "Tel Aviv", "team": "Platform"},
    }
]

ASHBY_PAYLOAD = {
    "jobs": [
        {
            "id": "9a6153da-639d-413e-b9bf-68ebf5f8c269",
            "title": "Backend Engineer",
            "jobUrl": "https://jobs.ashbyhq.com/acme/9a6153da-639d-413e-b9bf-68ebf5f8c269",
            "location": "TLV",
            "isListed": True,
        }
    ]
}


def test_normalise_greenhouse_reads_nested_location() -> None:
    """Greenhouse nests the location under its own key and issues integer ids."""
    [posting] = normalise(ATS.GREENHOUSE, GREENHOUSE_PAYLOAD)
    assert posting.external_id == "5101378008"
    assert posting.title == "Backend Engineer"
    assert posting.location_raw == "Tel Aviv, Israel"
    assert posting.url.endswith("/5101378008")


def test_normalise_lever_reads_bare_list_and_text_title() -> None:
    """Lever returns a list rather than an object, and calls the title ``text``."""
    [posting] = normalise(ATS.LEVER, LEVER_PAYLOAD)
    assert posting.external_id == "0808b2c0-80f7-478b-9067-812416ac0634"
    assert posting.title == "Backend Engineer"
    assert posting.location_raw == "Tel Aviv"


def test_normalise_ashby_reads_flat_location() -> None:
    """Ashby keeps the location as a plain string."""
    [posting] = normalise(ATS.ASHBY, ASHBY_PAYLOAD)
    assert posting.external_id == "9a6153da-639d-413e-b9bf-68ebf5f8c269"
    assert posting.location_raw == "TLV"


def test_normalise_ashby_drops_unlisted() -> None:
    """An unlisted Ashby posting is never stored, so it cannot later look like a closure."""
    payload = {"jobs": [{**ASHBY_PAYLOAD["jobs"][0], "isListed": False}]}
    assert normalise(ATS.ASHBY, payload) == []


def test_normalise_lever_survives_missing_categories() -> None:
    """A Lever posting with no categories has no location, which is not an error."""
    [posting] = normalise(ATS.LEVER, [{**LEVER_PAYLOAD[0], "categories": None}])
    assert posting.location_raw == ""


def _board_posting(external_id: str = "1", title: str = "Backend Engineer") -> BoardPosting:
    """Builds one normalised posting for reconcile tests."""
    return BoardPosting(
        external_id=external_id,
        url=f"https://example.test/jobs/{external_id}",
        title=title,
        location_raw="Tel Aviv",
    )


async def _company() -> Company:
    """Stores and returns a company to sweep."""
    return await Company(name="Acme", ats=ATS.GREENHOUSE, token="acme").insert()


async def test_reconcile_inserts_unseen_postings(
    db: AsyncMongoClient[dict[str, Any]],
) -> None:
    """A posting the board reports for the first time is stored as open."""
    company = await _company()

    result = await reconcile(company, [_board_posting()])

    assert result.added == 1
    stored = await Posting.find_one(Posting.external_id == "1")
    assert stored is not None
    assert stored.status is PostingStatus.OPEN
    assert stored.first_seen_at == stored.last_seen_at


async def test_reconcile_bumps_last_seen_without_duplicating(
    db: AsyncMongoClient[dict[str, Any]],
) -> None:
    """A posting still on the board moves ``last_seen_at`` in place rather than adding a row."""
    company = await _company()
    first = datetime(2026, 8, 1, tzinfo=UTC)
    later = first + timedelta(days=1)

    await reconcile(company, [_board_posting()], now=first)
    result = await reconcile(company, [_board_posting()], now=later)

    assert result.added == 0
    assert result.still_open == 1
    assert await Posting.find().count() == 1
    stored = await Posting.find_one(Posting.external_id == "1")
    assert stored is not None
    assert stored.first_seen_at == first
    assert stored.last_seen_at == later


async def test_reconcile_refreshes_edited_fields(
    db: AsyncMongoClient[dict[str, Any]],
) -> None:
    """Boards edit postings in place, so the stored copy follows the current wording."""
    company = await _company()
    await reconcile(company, [_board_posting(title="Backend Engineer")])

    await reconcile(company, [_board_posting(title="Backend Engineer, Platform")])

    stored = await Posting.find_one(Posting.external_id == "1")
    assert stored is not None
    assert stored.title == "Backend Engineer, Platform"


async def test_reconcile_tolerates_a_single_absence(
    db: AsyncMongoClient[dict[str, Any]],
) -> None:
    """One missing sweep is a board fault, not a closure, and must not be reported as one."""
    company = await _company()
    await reconcile(company, [_board_posting()])

    result = await reconcile(company, [])

    assert result.closed == 0
    stored = await Posting.find_one(Posting.external_id == "1")
    assert stored is not None
    assert stored.status is PostingStatus.OPEN
    assert stored.missed_sweeps == 1
    assert stored.closed_at is None


async def test_reconcile_closes_after_repeated_absence(
    db: AsyncMongoClient[dict[str, Any]],
) -> None:
    """Sustained absence is the only evidence a board gives that a role is gone."""
    company = await _company()
    await reconcile(company, [_board_posting()])
    closed_at = datetime(2026, 8, 5, tzinfo=UTC)

    for _ in range(MISSES_BEFORE_CLOSED - 1):
        await reconcile(company, [])
    result = await reconcile(company, [], now=closed_at)

    assert result.closed == 1
    stored = await Posting.find_one(Posting.external_id == "1")
    assert stored is not None
    assert stored.status is PostingStatus.CLOSED
    assert stored.closed_at == closed_at


async def test_reconcile_leaves_closed_postings_alone(
    db: AsyncMongoClient[dict[str, Any]],
) -> None:
    """A role that closed weeks ago is not re-closed on every later sweep."""
    company = await _company()
    await reconcile(company, [_board_posting()])
    for _ in range(MISSES_BEFORE_CLOSED):
        await reconcile(company, [])
    stored = await Posting.find_one(Posting.external_id == "1")
    assert stored is not None
    first_closed_at = stored.closed_at

    result = await reconcile(company, [])

    assert result.closed == 0
    stored = await Posting.find_one(Posting.external_id == "1")
    assert stored is not None
    assert stored.closed_at == first_closed_at


async def test_reconcile_reopens_a_returning_posting(
    db: AsyncMongoClient[dict[str, Any]],
) -> None:
    """The same identifier listed again means the board has it open, whatever happened between."""
    company = await _company()
    await reconcile(company, [_board_posting()])
    for _ in range(MISSES_BEFORE_CLOSED):
        await reconcile(company, [])

    result = await reconcile(company, [_board_posting()])

    assert result.reopened == 1
    assert await Posting.find().count() == 1
    stored = await Posting.find_one(Posting.external_id == "1")
    assert stored is not None
    assert stored.status is PostingStatus.OPEN
    assert stored.closed_at is None
    assert stored.missed_sweeps == 0


async def test_reconcile_ignores_other_companies_postings(
    db: AsyncMongoClient[dict[str, Any]],
) -> None:
    """One company's empty board must not close another company's roles."""
    acme = await _company()
    other = await Company(name="Other", ats=ATS.GREENHOUSE, token="other").insert()
    await reconcile(acme, [_board_posting()])

    result = await reconcile(other, [])

    assert result.closed == 0
    stored = await Posting.find_one(Posting.company_token == "acme")
    assert stored is not None
    assert stored.missed_sweeps == 0


async def test_reconcile_records_the_sweep_on_the_company(
    db: AsyncMongoClient[dict[str, Any]],
) -> None:
    """``last_swept_at`` is what a scheduled sweep will order its work by."""
    company = await _company()
    at = datetime(2026, 8, 9, tzinfo=UTC)

    await reconcile(company, [], now=at)

    refreshed = await Company.get(company.id)
    assert refreshed is not None
    assert refreshed.last_swept_at == at


def test_candidate_tokens_joins_and_hyphenates() -> None:
    """Multi-word companies spell their token both ways, so both are tried."""
    assert candidate_tokens("Cato Networks") == ["catonetworks", "cato-networks", "cato"]


def test_candidate_tokens_drops_a_legal_suffix() -> None:
    """No board token carries the legal suffix, so keeping it would guess a token nobody uses."""
    assert candidate_tokens("Lemonade Ltd.") == ["lemonade"]


def test_candidate_tokens_ignores_punctuation() -> None:
    """Tokens are letters and digits only, whatever the name is written with."""
    assert candidate_tokens("Wiz.io") == ["wizio", "wiz-io", "wiz"]


def test_candidate_tokens_does_not_repeat_a_single_word() -> None:
    """A one-word name yields one candidate, not the same string three times."""
    assert candidate_tokens("Lemonade") == ["lemonade"]


def test_candidate_tokens_rejects_a_nameless_name() -> None:
    """A name with no usable characters produces no guesses rather than an empty token.

    An empty token would build a board URL that means something else entirely.
    """
    assert candidate_tokens("  ---  ") == []


def _board_client(
    boards: dict[tuple[ATS, str], Any],
    faults: dict[tuple[ATS, str], int] | None = None,
) -> httpx.AsyncClient:
    """Builds a client serving the given boards, 404ing every other token as the real APIs do."""
    payloads = {
        BOARD_URLS[ats].format(token=token): payload for (ats, token), payload in boards.items()
    }
    fault_urls = {
        BOARD_URLS[ats].format(token=token): status
        for (ats, token), status in (faults or {}).items()
    }

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url in fault_urls:
            return httpx.Response(fault_urls[url], text="boom")
        if url in payloads:
            return httpx.Response(200, json=payloads[url])
        return httpx.Response(404, text="Not Found")

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_fetch_board_reads_the_board_its_token_addresses(
    db: AsyncMongoClient[dict[str, Any]],
) -> None:
    """A watched company's ATS and token build the URL, and the answer arrives normalised.

    The board is served at that one URL and every other 404s, so a URL built from anything else
    fails here rather than returning something the caller cannot tell apart from an empty board.
    """
    company = await _company()

    async with _board_client({(ATS.GREENHOUSE, "acme"): GREENHOUSE_PAYLOAD}) as client:
        [posting] = await fetch_board(company, client)

    assert posting.external_id == "5101378008"
    assert posting.title == "Backend Engineer"
    assert posting.location_raw == "Tel Aviv, Israel"


async def test_fetch_board_raises_on_an_error_status(
    db: AsyncMongoClient[dict[str, Any]],
) -> None:
    """A board that answers with an error has not reported an empty board.

    For these APIs an error status means the token is wrong, while a company with nothing open
    answers 200 with an empty list. Returning ``[]`` for both would let a sweep read a mistyped
    token as every posting having closed.
    """
    company = await _company()

    async with _board_client({}, faults={(ATS.GREENHOUSE, "acme"): 500}) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await fetch_board(company, client)


async def test_resolve_finds_the_board_a_name_answers_on() -> None:
    """The point of the resolver: a name in, the system and token that serve it out."""
    async with _board_client({(ATS.ASHBY, "lemonade"): ASHBY_PAYLOAD}) as client:
        assert await resolve("Lemonade Ltd.", client) == [
            BoardMatch(ats=ATS.ASHBY, token="lemonade", job_count=1)
        ]


async def test_resolve_finds_nothing_when_every_candidate_is_unknown() -> None:
    """An unresolvable name is an ordinary answer, not an error."""
    async with _board_client({}) as client:
        assert await resolve("No Such Company", client) == []


async def test_resolve_reports_an_empty_board_as_a_match() -> None:
    """A company with a board but no openings is on the watchlist; it just has nothing today."""
    async with _board_client({(ATS.LEVER, "acme"): []}) as client:
        assert await resolve("Acme", client) == [
            BoardMatch(ats=ATS.LEVER, token="acme", job_count=0)
        ]


async def test_resolve_reports_every_match_rather_than_the_first() -> None:
    """One token can answer on two systems, and only a person can say which company it is."""
    boards = {
        (ATS.GREENHOUSE, "acme"): GREENHOUSE_PAYLOAD,
        (ATS.LEVER, "acme"): LEVER_PAYLOAD,
    }
    async with _board_client(boards) as client:
        matches = await resolve("Acme", client)

    assert [match.ats for match in matches] == [ATS.GREENHOUSE, ATS.LEVER]


async def test_resolve_raises_rather_than_reading_an_outage_as_absence() -> None:
    """A 500 means the board is unwell, not that the company has no board.

    Swallowing it would drop a resolvable company from the watchlist for the length of an outage.
    """
    async with _board_client({}, faults={(ATS.GREENHOUSE, "acme"): 500}) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await resolve("Acme", client)


async def test_watch_stores_a_confirmed_match(
    db: AsyncMongoClient[dict[str, Any]],
) -> None:
    """A confirmed board becomes a company the sweep will read."""
    company = await watch("Lemonade", BoardMatch(ats=ATS.ASHBY, token="lemonade", job_count=34))

    assert company.id is not None
    stored = await Company.find_one(Company.token == "lemonade")
    assert stored is not None
    assert stored.name == "Lemonade"
    assert stored.ats is ATS.ASHBY


async def test_watch_does_not_duplicate_a_board(
    db: AsyncMongoClient[dict[str, Any]],
) -> None:
    """Re-running a seed list must be harmless, so the same board resolves to the same entry."""
    match = BoardMatch(ats=ATS.ASHBY, token="lemonade", job_count=34)
    first = await watch("Lemonade", match)

    again = await watch("Lemonade Ltd.", match)

    assert again.id == first.id
    assert await Company.find().count() == 1


async def test_watch_keeps_the_existing_sweep_history(
    db: AsyncMongoClient[dict[str, Any]],
) -> None:
    """Re-adding a watched company must not make its board look never-swept.

    A reset ``last_swept_at`` would re-seed the whole board as newly discovered.
    """
    match = BoardMatch(ats=ATS.ASHBY, token="lemonade", job_count=34)
    company = await watch("Lemonade", match)
    swept_at = datetime(2026, 8, 12, tzinfo=UTC)
    await company.set({"last_swept_at": swept_at})

    again = await watch("Lemonade", match)

    assert again.last_swept_at == swept_at


async def test_watch_treats_one_token_on_two_systems_as_two_boards(
    db: AsyncMongoClient[dict[str, Any]],
) -> None:
    """The same slug on two systems is two different boards, and both may be worth watching."""
    await watch("Acme", BoardMatch(ats=ATS.GREENHOUSE, token="acme", job_count=1))
    await watch("Acme", BoardMatch(ats=ATS.LEVER, token="acme", job_count=1))

    assert await Company.find().count() == 2
