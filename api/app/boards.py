"""Reading company job boards and reconciling what they return against stored postings.

Three applicant-tracking systems publish a company's open roles as JSON with no key and no
scraping. Their payloads disagree on almost everything — Lever returns a bare list while the other
two wrap one, and all three name the title, link and location differently — so every board is
normalised to ``BoardPosting`` before any logic touches it.

Boards are addressed by a token, which is the company's slug in its ATS rather than its name.
``resolve`` guesses that token from a name, which is how the watchlist gets built without a search
API.

Reconciling is where the value is. Comparing a board against what was stored last time turns three
things into signal that no board reports directly: a posting that disappeared, one that is still
listed weeks after applying, and one that came back.
"""

import html
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import httpx
from pydantic import BaseModel

from app.models import ATS, Company, Posting, PostingStatus

BOARD_URLS: dict[ATS, str] = {
    ATS.GREENHOUSE: "https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true",
    ATS.LEVER: "https://api.lever.co/v0/postings/{token}?mode=json",
    ATS.ASHBY: "https://api.ashbyhq.com/posting-api/job-board/{token}",
}

MISSES_BEFORE_CLOSED = 2
"""How many consecutive sweeps must miss a posting before it counts as closed.

Boards intermittently omit entries that are still live. Closing on the first absence would report
roles as filled while they are still taking applications, which is the one failure this feature
cannot afford — the whole point is to tell the user when to stop waiting.
"""


class BoardPosting(BaseModel):
    """One open posting as a board reports it, in the shape the rest of the code works with.

    Deliberately not a Document: this is what a board said during one fetch, not something stored.
    What gets stored is ``Posting``, which additionally carries the history the board has no
    concept of.
    """

    external_id: str
    url: str
    title: str
    location_raw: str
    description: str = ""
    """The posting body as plain text, with any markup stripped.

    All three systems return this in the same response as the listing, so reading it costs no
    extra request — only a larger payload. It is what the technologies and the years of
    experience are named in; the title says neither.

    Defaults to empty because a board may omit it, and an absent description must not be
    mistaken for one that mentions nothing.
    """


class SweepResult(BaseModel):
    """What one reconcile changed, for logging and for the tests to assert on.

    The counts are of postings, not of database operations, and they partition the board: every
    posting seen is either added or still open, and every stored posting not seen either counts
    towards closure or has already closed.
    """

    added: int = 0
    still_open: int = 0
    closed: int = 0
    reopened: int = 0


def _plain_text(markup: str) -> str:
    """Turns a posting body into plain text.

    Greenhouse returns HTML with its entities escaped a second time, so the entities are unescaped
    twice before tags are removed — once for the outer escaping, once for the markup itself.
    Skipping either leaves literal ``&lt;p&gt;`` in the text, which no keyword then matches
    across.

    Args:
        markup: The body as the board returned it, HTML or plain.

    Returns:
        The same text with tags gone and whitespace collapsed.
    """
    text = html.unescape(html.unescape(markup))
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()


def _normalise_greenhouse(payload: Any) -> list[BoardPosting]:
    """Maps a Greenhouse board payload to the common shape.

    Greenhouse issues integer posting ids; they are stored as strings so that one field type
    serves all three systems, the other two of which issue UUIDs.
    """
    return [
        BoardPosting(
            external_id=str(job["id"]),
            url=job["absolute_url"],
            title=job["title"],
            location_raw=(job.get("location") or {}).get("name", ""),
            description=_plain_text(job.get("content") or ""),
        )
        for job in payload.get("jobs", [])
    ]


def _normalise_lever(payload: Any) -> list[BoardPosting]:
    """Maps a Lever board payload to the common shape.

    Lever returns a bare list rather than an object, and calls the title ``text``. Its location
    sits inside ``categories``, which is absent on postings that were never given one.
    """
    return [
        BoardPosting(
            external_id=str(job["id"]),
            url=job["hostedUrl"],
            title=job["text"],
            location_raw=(job.get("categories") or {}).get("location", ""),
            description=_plain_text(
                " ".join(
                    str(job.get(field) or "")
                    for field in ("descriptionPlain", "additionalPlain")
                )
            ),
        )
        for job in payload
    ]


def _normalise_ashby(payload: Any) -> list[BoardPosting]:
    """Maps an Ashby board payload to the common shape.

    Ashby exposes unlisted postings alongside live ones, so entries whose ``isListed`` is false are
    dropped here rather than being stored and later mistaken for roles that closed.
    """
    return [
        BoardPosting(
            external_id=str(job["id"]),
            url=job["jobUrl"],
            title=job["title"],
            location_raw=job.get("location") or "",
            description=_plain_text(job.get("descriptionPlain") or ""),
        )
        for job in payload.get("jobs", [])
        if job.get("isListed", True)
    ]


_NORMALISERS = {
    ATS.GREENHOUSE: _normalise_greenhouse,
    ATS.LEVER: _normalise_lever,
    ATS.ASHBY: _normalise_ashby,
}


def normalise(ats: ATS, payload: Any) -> list[BoardPosting]:
    """Converts one board's raw payload into the common shape.

    Kept separate from fetching so the per-system quirks can be tested against recorded payloads
    without a network call.

    Args:
        ats: Which system produced the payload.
        payload: The decoded JSON body, whose top-level type differs by system.

    Returns:
        Every listed posting on the board.
    """
    return _NORMALISERS[ats](payload)


async def fetch_board(company: Company, client: httpx.AsyncClient) -> list[BoardPosting]:
    """Reads one company's board and returns its listed postings.

    The client is passed in rather than created here so that a sweep over many companies reuses one
    connection pool, and so tests can supply a transport instead of reaching the network.

    Args:
        company: The company whose board to read; its ATS and token build the URL.
        client: An HTTP client to issue the request with.

    Returns:
        Every listed posting on the board.

    Raises:
        httpx.HTTPStatusError: If the board responds with an error status, which for these APIs
            means the token is wrong rather than that the company has no openings — an empty board
            is a 200 with an empty list.
    """
    response = await client.get(BOARD_URLS[company.ats].format(token=company.token))
    response.raise_for_status()
    return normalise(company.ats, response.json())


async def reconcile(
    company: Company,
    seen: Sequence[BoardPosting],
    now: datetime | None = None,
) -> SweepResult:
    """Records one board reading against what was stored from previous readings.

    A posting present on the board is either new, or one already known whose ``last_seen_at`` moves
    forward. Its title, URL and location are refreshed at the same time, because boards edit
    postings in place and the stored copy should describe the role as it stands.

    A posting absent from the board has its miss counter raised, and closes once the counter
    reaches ``MISSES_BEFORE_CLOSED``. Already-closed postings are left alone, so a role that closed
    weeks ago is not repeatedly rewritten.

    A closed posting that reappears is reopened rather than left closed or duplicated: the same
    identifier returning means the board is listing it again, whether it was relisted or the
    earlier absences were a board fault.

    Everything is timestamped from a single ``now`` so that one sweep produces one instant, rather
    than a spread that makes ordering within the sweep look meaningful.

    Args:
        company: The company whose board was read.
        seen: The postings that board returned.
        now: Instant to record this sweep at; defaults to the current time. Tests pass an explicit
            value to advance time without waiting.

    Returns:
        Counts of what changed.
    """
    at = now or datetime.now(UTC)
    result = SweepResult()

    stored = await Posting.find(
        Posting.ats == company.ats,
        Posting.company_token == company.token,
    ).to_list()
    by_id = {posting.external_id: posting for posting in stored}
    seen_ids = {posting.external_id for posting in seen}

    for board_posting in seen:
        existing = by_id.get(board_posting.external_id)
        if existing is None:
            await Posting(
                company_token=company.token,
                ats=company.ats,
                external_id=board_posting.external_id,
                url=board_posting.url,
                title=board_posting.title,
                location_raw=board_posting.location_raw,
                description=board_posting.description,
                first_seen_at=at,
                last_seen_at=at,
            ).insert()
            result.added += 1
            continue

        changes: dict[str, Any] = {
            "last_seen_at": at,
            "missed_sweeps": 0,
            "url": board_posting.url,
            "title": board_posting.title,
            "location_raw": board_posting.location_raw,
            "description": board_posting.description,
        }
        if existing.status is PostingStatus.CLOSED:
            changes["status"] = PostingStatus.OPEN
            changes["closed_at"] = None
            result.reopened += 1
        else:
            result.still_open += 1
        await existing.set(changes)

    for posting in stored:
        if posting.external_id in seen_ids or posting.status is PostingStatus.CLOSED:
            continue
        misses = posting.missed_sweeps + 1
        changes = {"missed_sweeps": misses}
        if misses >= MISSES_BEFORE_CLOSED:
            changes["status"] = PostingStatus.CLOSED
            changes["closed_at"] = at
            result.closed += 1
        await posting.set(changes)

    await company.set({"last_swept_at": at, "updated_at": at})
    return result


_LEGAL_SUFFIXES = frozenset(
    {"ltd", "limited", "inc", "incorporated", "llc", "corp", "corporation", "co", "gmbh", "plc"}
)
"""Trailing words that belong to a company's legal name but never to its board token."""


class BoardMatch(BaseModel):
    """A board that answered to one guessed token.

    ``job_count`` is reported because an empty board is a real board — several confirmed companies
    currently list nothing — so it separates "no such company here" from "here, but not hiring".
    """

    ats: ATS
    token: str
    job_count: int


def candidate_tokens(name: str) -> list[str]:
    """Guesses the board tokens a company name might use.

    Tokens are lowercase and punctuation-free, so the name is reduced to its words and rejoined
    the two ways these systems spell multi-word companies. The first word alone is tried last,
    because companies routinely register a board under the short form of their name.

    Args:
        name: The company name as a human writes it.

    Returns:
        Candidates in the order they should be tried, most specific first, without duplicates.
        Empty if the name contains nothing that could form a token.
    """
    words = [word for word in re.split(r"[^a-z0-9]+", name.lower()) if word]
    while len(words) > 1 and words[-1] in _LEGAL_SUFFIXES:
        words.pop()
    if not words:
        return []
    return list(dict.fromkeys(["".join(words), "-".join(words), words[0]]))


async def resolve(name: str, client: httpx.AsyncClient) -> list[BoardMatch]:
    """Finds which boards, if any, a company name resolves to.

    Every candidate is tried against every system rather than stopping at the first hit, because
    a token can answer on two systems at once and nothing in these payloads identifies the company
    well enough to pick between them. That judgement is left to a person, so this reports and does
    not store.

    A 404 is these APIs' way of saying no such board, and is the only status read as absence. Any
    other error status is a fault, and is raised rather than quietly recorded as "no board" —
    which would drop a company off the watchlist for the lifetime of an outage.

    Args:
        name: The company name to resolve.
        client: An HTTP client to issue the requests with.

    Returns:
        Every board that answered, which may be none and may be more than one.

    Raises:
        httpx.HTTPStatusError: If a board responds with an error status other than 404.
    """
    matches: list[BoardMatch] = []
    for token in candidate_tokens(name):
        for ats, url in BOARD_URLS.items():
            response = await client.get(url.format(token=token))
            if response.status_code == httpx.codes.NOT_FOUND:
                continue
            response.raise_for_status()
            matches.append(
                BoardMatch(ats=ats, token=token, job_count=len(normalise(ats, response.json())))
            )
    return matches


async def watch(name: str, match: BoardMatch) -> Company:
    """Puts a confirmed board on the watchlist, or returns the entry already there.

    Idempotent on the ATS and token together, which is the pair the unique index enforces and the
    pair that identifies a board. Re-running a seed list, or resolving a company that was added
    months ago, must not create a second entry or reset the sweep history on the first — a company
    whose ``last_swept_at`` silently went back to null would re-seed its whole board as new.

    The name is only a label, so an entry that already exists keeps the name it was stored with
    rather than being rewritten by whatever spelling resolved it this time.

    Args:
        name: The company name to label the entry with, used only if it is being created.
        match: A board confirmed to belong to this company.

    Returns:
        The watchlist entry, whether it was just created or already existed.
    """
    existing = await Company.find_one(Company.ats == match.ats, Company.token == match.token)
    if existing is not None:
        return existing
    return await Company(name=name, ats=match.ats, token=match.token).insert()
