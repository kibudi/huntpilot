"""Tests for the scheduled sweep over the whole watchlist.

Nothing here reaches the network: every board is served by an ``httpx.MockTransport``, the same
approach ``test_boards.py`` uses, so a board that 500s or hangs is something a test can arrange
rather than wait for.
"""

import asyncio
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from pymongo import AsyncMongoClient

from app.boards import BOARD_URLS
from app.models import ATS, Company, Posting, PostingStatus
from app.sweep import SweepSummary, sweep
from app.worker import SWEEP_INTERVAL, celery_app, sweep_boards

MATCHING_DESCRIPTION = "We build with Python, FastAPI and MongoDB. 2 years of experience."
"""A body that survives ``relevant``: every technology it names is known, and the bar is low."""

MISMATCHED_DESCRIPTION = "Java, Spring Boot and Kafka, with 8 years of experience."
"""A body that ``relevant`` discards, so a sweep can be shown to filter before it stores."""


def _greenhouse_board(
    posting_id: int = 1,
    title: str = "Backend Engineer",
    description: str = MATCHING_DESCRIPTION,
) -> dict[str, Any]:
    """Builds a one-posting Greenhouse payload in Tel Aviv."""
    return {
        "jobs": [
            {
                "id": posting_id,
                "title": title,
                "absolute_url": f"https://job-boards.greenhouse.io/acme/jobs/{posting_id}",
                "location": {"name": "Tel Aviv, Israel"},
                "content": description,
            }
        ]
    }


def _board_client(
    boards: dict[str, Any],
    faults: dict[str, int] | None = None,
) -> httpx.AsyncClient:
    """Builds a client serving the given Greenhouse tokens, 404ing every other as the API does.

    Faults are given as a token to a status code, which is how a board is made to fail without
    anything in the sweep knowing it was arranged.
    """
    payloads = {
        BOARD_URLS[ATS.GREENHOUSE].format(token=token): board for token, board in boards.items()
    }
    fault_urls = {
        BOARD_URLS[ATS.GREENHOUSE].format(token=token): status
        for token, status in (faults or {}).items()
    }

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url in fault_urls:
            return httpx.Response(fault_urls[url], text="boom")
        if url in payloads:
            return httpx.Response(200, json=payloads[url])
        return httpx.Response(404, text="Not Found")

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _watch(token: str) -> Company:
    """Puts one Greenhouse board on the watchlist."""
    return await Company(name=token.title(), ats=ATS.GREENHOUSE, token=token).insert()


async def _open_posting(token: str, external_id: str = "1") -> Posting:
    """Stores one open posting for a watched company, as an earlier sweep would have."""
    return await Posting(
        company_token=token,
        ats=ATS.GREENHOUSE,
        external_id=external_id,
        url="https://example.com/jobs/1",
        title="Backend Engineer",
        location_raw="Tel Aviv, Israel",
        description=MATCHING_DESCRIPTION,
        first_seen_at=datetime(2026, 8, 1, tzinfo=UTC),
        last_seen_at=datetime(2026, 8, 1, tzinfo=UTC),
    ).insert()


async def test_sweep_reads_every_watched_board(
    db: AsyncMongoClient[dict[str, Any]],
) -> None:
    """The loop the feature exists for: every company on the watchlist, one pass, totalled."""
    await _watch("acme")
    await _watch("globex")

    async with _board_client(
        {"acme": _greenhouse_board(1), "globex": _greenhouse_board(2)}
    ) as client:
        summary = await sweep(client)

    assert summary == SweepSummary(boards_swept=2, added=2)
    assert await Posting.find().count() == 2


async def test_sweep_filters_before_storing(
    db: AsyncMongoClient[dict[str, Any]],
) -> None:
    """``relevant`` runs between the fetch and the reconcile, not after storage.

    A posting stored despite failing the filter would later be reported as closing when the board
    dropped it, which is signal about a role that was never worth surfacing.
    """
    await _watch("acme")

    async with _board_client(
        {"acme": _greenhouse_board(1, description=MISMATCHED_DESCRIPTION)}
    ) as client:
        summary = await sweep(client)

    assert summary.boards_swept == 1
    assert summary.added == 0
    assert await Posting.find().count() == 0


async def test_sweep_survives_a_board_that_fails(
    db: AsyncMongoClient[dict[str, Any]],
) -> None:
    """The property the whole design turns on: one bad board does not end the pass.

    The failing company is first in the watchlist, so a sweep that let the error escape would
    never reach the second board at all.
    """
    await _watch("acme")
    await _watch("globex")

    async with _board_client(
        {"globex": _greenhouse_board(2)}, faults={"acme": 500}
    ) as client:
        summary = await sweep(client)

    assert summary.boards_swept == 1
    assert summary.boards_failed == 1
    assert summary.added == 1
    assert [failure.token for failure in summary.failures] == ["acme"]
    assert await Posting.find().count() == 1


async def test_sweep_survives_a_board_that_answers_nonsense(
    db: AsyncMongoClient[dict[str, Any]],
) -> None:
    """A board can break the sweep without ever returning an error status.

    A 200 whose body is not the shape the system documents raises out of normalising, not out of
    HTTP. Containment has to cover that too, or the sweep is only protected against the failure
    mode that happens to be easiest to imagine.
    """
    await _watch("acme")
    await _watch("globex")

    async with _board_client(
        {"acme": {"jobs": [{"nothing": "expected"}]}, "globex": _greenhouse_board(2)}
    ) as client:
        summary = await sweep(client)

    assert summary.boards_swept == 1
    assert summary.boards_failed == 1
    assert summary.added == 1


async def test_a_failing_board_does_not_move_its_postings_towards_closed(
    db: AsyncMongoClient[dict[str, Any]],
) -> None:
    """The failure this feature cannot afford: an unreadable board reading as an empty one.

    Closure is inferred from absence, so reconciling a failed fetch against an empty list would
    count a miss against every open posting the company has, and two such sweeps would close roles
    that are still taking applications. A board that could not be read must leave storage exactly
    as it was.
    """
    await _watch("acme")
    stored = await _open_posting("acme")

    async with _board_client({}, faults={"acme": 500}) as client:
        summary = await sweep(client)

    assert summary.boards_failed == 1
    refreshed = await Posting.get(stored.id)
    assert refreshed is not None
    assert refreshed.missed_sweeps == 0
    assert refreshed.status is PostingStatus.OPEN


async def test_a_failing_board_does_not_record_a_successful_sweep(
    db: AsyncMongoClient[dict[str, Any]],
) -> None:
    """``last_swept_at`` means the board was read, so a failed board must not claim one.

    It is the field a future run would order or skip work by, and a company whose board has been
    404ing for a week must not look freshly swept.
    """
    company = await _watch("acme")

    async with _board_client({}, faults={"acme": 500}) as client:
        await sweep(client)

    refreshed = await Company.get(company.id)
    assert refreshed is not None
    assert refreshed.last_swept_at is None


async def test_a_cancelled_sweep_still_stops(
    db: AsyncMongoClient[dict[str, Any]],
) -> None:
    """Cancellation must end the sweep, not be filed as one more board that failed.

    The failure rule swallows anything a board can raise so that no company can end the pass. That
    rule has to stop short of ``BaseException``: a cancelled task raises ``CancelledError``, and
    catching it would let a sweep the runtime is trying to kill carry on through the rest of the
    watchlist, reporting the cancellation as an ordinary board fault.
    """
    await _watch("acme")

    def handler(request: httpx.Request) -> httpx.Response:
        raise asyncio.CancelledError

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    async with client:
        with pytest.raises(asyncio.CancelledError):
            await sweep(client)


async def test_sweep_reports_nothing_when_the_watchlist_is_empty(
    db: AsyncMongoClient[dict[str, Any]],
) -> None:
    """An empty watchlist is not an error: it is a sweep with nothing to do."""
    async with _board_client({}) as client:
        assert await sweep(client) == SweepSummary()


def test_beat_schedules_the_task_that_exists() -> None:
    """Beat's entry names the task by string, which is how it silently schedules nothing.

    A rename of the task or its ``name=`` argument leaves this schedule pointing at a task no
    worker has registered; Beat still enqueues it every six hours and every message is rejected as
    unregistered. Asserting the two agree is the only cheap way to notice.
    """
    entry = celery_app.conf.beat_schedule["sweep-boards"]

    assert entry["task"] == sweep_boards.name
    assert entry["task"] in celery_app.tasks
    assert entry["schedule"] == SWEEP_INTERVAL
