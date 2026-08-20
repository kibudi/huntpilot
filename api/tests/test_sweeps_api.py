"""Tests for starting a sweep, refusing a second one, and reading the history.

``test_sweep.py`` covers what one pass over the watchlist does. This covers the bookkeeping around
it: that a run is recorded before any board is read, that two sweeps cannot overlap, and that a
sweep whose process died stops holding the lock.

The concurrency rule is the subject here, and it is the one worth stating plainly. Two passes over
the same postings interleave their reconciles, and the second reads the first's writes as board
state — which, in a system that infers closure from absence, is how a live job gets marked closed.
Asking whether a sweep is running and then recording one are two round trips, so the check alone
can only ever be advisory; the refusal has to come from a unique index. The test that matters is
therefore the one that starts two sweeps *at once* rather than one after the other, because only
that one fails when the index is removed.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from pymongo import AsyncMongoClient

from app.main import _sweeps_in_flight
from app.models import SweepRun, SweepState
from app.sweep import (
    STALE_AFTER,
    SweepInProgress,
    _connected_sweep,
    claim_run,
    finish_run,
    running_run,
)


async def _settle() -> None:
    """Waits for the sweeps this process started in the background to finish.

    A run started through the API detaches from the request, so without this a test would drop the
    database while a task was still writing to it — a failure that would land in whichever test ran
    next rather than in the one that caused it.
    """
    await asyncio.gather(*tuple(_sweeps_in_flight), return_exceptions=True)


async def _stale_run() -> SweepRun:
    """Stores a run that started longer ago than any sweep could still be going."""
    run = SweepRun()
    run.started_at = datetime.now(UTC) - STALE_AFTER - timedelta(minutes=1)
    return await run.insert()


async def test_starting_a_sweep_records_it_before_any_board_is_read(api: AsyncClient) -> None:
    """The response is a run in progress, not a result.

    A pass takes minutes, so the point of the endpoint is to hand back something to poll. A reply
    that waited for the summary would be the blocking call this exists to avoid, and ``202`` rather
    than ``201`` says the work is accepted rather than done.
    """
    response = await api.post("/api/sweeps")

    assert response.status_code == 202
    assert response.json()["state"] == "running"
    assert response.json()["summary"] is None
    await _settle()


async def test_a_second_sweep_is_refused_while_one_is_running(api: AsyncClient) -> None:
    """The refusal names when the sweep in the way started, so the reply is actionable."""
    first = await api.post("/api/sweeps")
    await SweepRun.get(first.json()["id"])

    second = await api.post("/api/sweeps")

    assert second.status_code == 409
    assert "already running" in second.json()["detail"]
    await _settle()


async def test_two_sweeps_starting_at_once_leave_one_run(
    db: AsyncMongoClient[dict[str, Any]],
) -> None:
    """The lock is the database's, not a lookup's — the test the whole design turns on.

    Both claims read "nothing running" before either writes, which is exactly the interleaving a
    check-then-insert cannot survive. Only the unique partial index refuses the second, so this is
    the test that fails when that index is dropped; starting two sweeps in sequence would pass
    either way and prove nothing.
    """
    results = await asyncio.gather(claim_run(), claim_run(), return_exceptions=True)

    claimed = [result for result in results if isinstance(result, SweepRun)]
    refused = [result for result in results if isinstance(result, SweepInProgress)]
    assert len(claimed) == 1
    assert len(refused) == 1
    assert await SweepRun.find(SweepRun.state == SweepState.RUNNING).count() == 1


async def test_a_sweep_whose_process_died_stops_holding_the_lock(
    db: AsyncMongoClient[dict[str, Any]],
) -> None:
    """A run older than any real pass is retired, and the next sweep is allowed to start.

    Without this a killed container would leave a run in ``running`` for ever and every later
    sweep would be refused — the feature failing permanently on the strength of one crash.
    """
    dead = await _stale_run()

    claimed = await claim_run()

    assert claimed.id != dead.id
    retired = await SweepRun.get(dead.id)
    assert retired is not None
    assert retired.state == SweepState.ABANDONED
    assert retired.finished_at is not None


async def test_every_stale_run_is_retired_not_only_the_first(
    db: AsyncMongoClient[dict[str, Any]],
) -> None:
    """Stopping at the first live run would strand the rest in ``running`` for ever.

    A database written before the unique index existed can hold several running runs. One of them
    left behind still occupies the index, so the very next sweep is refused with nothing a user can
    do about it — the stuck lock the staleness rule exists to prevent.

    The index is dropped for the duration, because it is what makes this state unreachable now and
    the state being tested is one only an older build could have written. The ``db`` fixture drops
    the whole database afterwards, so nothing is left to restore.
    """
    await SweepRun.get_pymongo_collection().drop_index("one_running_sweep")
    await _stale_run()
    await _stale_run()
    live = await SweepRun().insert()

    still_going = await running_run()

    assert still_going is not None
    assert still_going.id == live.id
    assert await SweepRun.find(SweepRun.state == SweepState.ABANDONED).count() == 2


async def test_a_live_run_is_not_retired(db: AsyncMongoClient[dict[str, Any]]) -> None:
    """A sweep that started a moment ago is busy, not dead.

    The guard against the staleness rule being written the wrong way round, which would declare
    every running sweep abandoned the instant it started and let every pass overlap.
    """
    live = await SweepRun().insert()

    still_going = await running_run()

    assert still_going is not None
    assert still_going.id == live.id
    stored = await SweepRun.get(live.id)
    assert stored is not None
    assert stored.state == SweepState.RUNNING


async def test_a_sweep_that_raises_is_recorded_as_failed(
    db: AsyncMongoClient[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run must reach a final state even when the pass blows up.

    Otherwise the exception is swallowed by a background task and the run sits in ``running``,
    blocking every sweep after it until it goes stale an hour later.
    """

    async def explode(client: httpx.AsyncClient) -> None:
        raise RuntimeError("the profile is unusable")

    monkeypatch.setattr("app.sweep.sweep", explode)
    run = await claim_run()

    await finish_run(run)

    stored = await SweepRun.get(run.id)
    assert stored is not None
    assert stored.state == SweepState.FAILED
    assert "the profile is unusable" in (stored.error or "")
    assert stored.finished_at is not None


async def test_a_finished_sweep_is_recorded_as_completed(
    db: AsyncMongoClient[dict[str, Any]],
) -> None:
    """An empty watchlist is a completed sweep with a summary, not a failure."""
    run = await finish_run(await claim_run())

    stored = await SweepRun.get(run.id)
    assert stored is not None
    assert stored.state == SweepState.COMPLETED
    assert stored.summary is not None
    assert stored.summary.boards_swept == 0


async def test_the_scheduled_sweep_is_skipped_while_a_manual_one_runs(
    db: AsyncMongoClient[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Beat firing on top of a dashboard-triggered pass must not start a second one.

    The scheduled path used to insert its run directly instead of claiming it, so the 409 the API
    returns protected nothing: a sweep started from the dashboard at 11:59 was joined by Beat's at
    12:00. Both paths go through ``claim_run`` now, and this is what says so.
    """

    class _AlreadyOpen:
        """Stands in for the connection the scheduled path opens for itself."""

        async def close(self) -> None:
            """Does nothing: the fixture owns the connection these tests share."""

    monkeypatch.setattr("app.sweep.init_db", lambda: asyncio.sleep(0, _AlreadyOpen()))
    await SweepRun().insert()

    assert await _connected_sweep() is None

    assert await SweepRun.find(SweepRun.state == SweepState.RUNNING).count() == 1


async def test_history_is_newest_first(db: AsyncMongoClient[dict[str, Any]]) -> None:
    """The run a client wants is the one happening now, which is the one with no finish."""
    older = SweepRun()
    older.started_at = datetime.now(UTC) - timedelta(hours=2)
    older.state = SweepState.COMPLETED
    await older.insert()
    newer = await SweepRun().insert()

    from app.main import list_sweeps

    history = await list_sweeps()

    assert [run.id for run in history] == [str(newer.id), str(older.id)]
