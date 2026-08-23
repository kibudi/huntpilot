"""Reading every watched board in one pass, on a schedule and by hand.

Boards are read serially, sharing one client. A sweep runs every six hours against a few dozen
public APIs, so nothing is waiting on it, and a serial pass keeps one board's failure local.

The failure rule matters more than anything else here. Closure is inferred from absence, so a
board that could not be read must produce *no* reconcile at all — handing ``reconcile`` an empty
list after a failed fetch would report every one of that company's roles as heading for closed.
Hence the fetch and the reconcile share one ``try``: anything that can go wrong before a board
reading is known-good has to land in the same place.

Every pass is recorded as a ``SweepRun``, whichever way it was started. A sweep takes minutes, so
whoever asked for one has nothing to look at until it is over unless the fact that it is happening
is written down first; and the two ways of starting one — the scheduled task and a manual
trigger — have to file the same record, or the history would be whichever half of the sweeps went
through the path that kept notes.
"""

import asyncio
from contextlib import suppress
from datetime import UTC, datetime, timedelta

import httpx
from pymongo.errors import DuplicateKeyError

from app.boards import fetch_board, reconcile
from app.db import init_db
from app.models import BoardFailure, Company, SweepRun, SweepState, SweepSummary
from app.profile import active_profile
from app.relevance import relevant

BOARD_TIMEOUT = httpx.Timeout(20.0)
"""How long any single board request may take.

Longer than httpx's five-second default because these responses carry every posting's full body,
which on the larger boards is megabytes. The default turns those boards into timeouts, and a
timeout here is indistinguishable from a board that could not be read at all.
"""

STALE_AFTER = timedelta(hours=1)
"""How long a run may sit in ``RUNNING`` before it is treated as dead rather than as busy.

A sweep that dies mid-pass — a killed container, a worker restarted mid-deploy — cannot write its
own final state, so without this the run would stay ``RUNNING`` for ever and every later sweep
would be refused as concurrent. An hour is well past any real pass: the seeded watchlist is a few
dozen boards read serially, and even if every one of them hit the twenty-second timeout the whole
thing would be over in twenty minutes.

The cost is that a sweep genuinely still running after an hour stops holding the lock, and a second
one could start alongside it. That is the right way round: two sweeps overlapping is untidy, while
a stuck lock means the feature never works again without someone opening the database.
"""


def board_client() -> httpx.AsyncClient:
    """Builds the HTTP client one pass reads every board with.

    A function rather than an inline constructor so the timeout and the redirect policy every
    board is read under are settled in one place, rather than at each of the two call sites that
    open a pass. ``sweep`` takes a client instead of building one, which is what lets a test drive
    a pass against a transport that never leaves the process.
    """
    return httpx.AsyncClient(timeout=BOARD_TIMEOUT, follow_redirects=True)


async def sweep(client: httpx.AsyncClient) -> SweepSummary:
    """Reads every watched board, stores what is worth storing, and reports what changed.

    ``Exception`` is caught rather than the HTTP errors alone, because no single company may end
    the sweep and the ways a board can disappoint are not confined to one library.
    ``BaseException`` is deliberately not caught, so a cancelled sweep still stops.

    The stored profile is read here, at the edge, and handed to ``relevant``. It is one of the two
    places that read it — every filter it drives takes the profile as an argument — and reading it
    once, before the first board, means one pass judges every board by the same rules even if the
    dashboard edits the search while the pass is running.

    Args:
        client: An HTTP client to read every board with, shared across the pass.

    Returns:
        Totals across the boards that answered, plus a record of the ones that did not.

    Raises:
        ProfileError: If the stored profile cannot be read or is no longer usable. Raised rather
            than caught, because a sweep with no profile has no filter and would either store
            everything or nothing.
    """
    profile = await active_profile()
    summary = SweepSummary()

    for company in await Company.find_all().to_list():
        try:
            postings = await fetch_board(company, client)
            result = await reconcile(company, relevant(postings, profile))
        except Exception as error:
            summary.boards_failed += 1
            summary.failures.append(
                BoardFailure(
                    name=company.name,
                    ats=company.ats,
                    token=company.token,
                    error=f"{type(error).__name__}: {error}",
                )
            )
            continue

        summary.boards_swept += 1
        summary.added += result.added
        summary.still_open += result.still_open
        summary.closed += result.closed
        summary.reopened += result.reopened

    return summary


async def running_run() -> SweepRun | None:
    """Returns the sweep currently in progress, retiring any that stopped without saying so.

    The one place that answers "is a sweep happening", so that refusing a second one and cleaning
    up after a dead one are the same question rather than two rules that can disagree.

    A run older than ``STALE_AFTER`` is marked ``ABANDONED`` here rather than by a reaper of its
    own. Nothing else needs to run for it to happen, and the moment it matters is exactly the
    moment somebody tries to start a sweep — which is when this is called. The visible cost is that
    a dead run keeps saying ``running`` in the history until the next attempt, which is one request
    away and only shows up on a screen nobody is watching.

    ``finished_at`` on an abandoned run is when it was declared dead, not when it stopped: nothing
    observed the process ending, so that instant is unknowable and a null would leave the dashboard
    with a run that never ends.

    Every stale run is retired, not just the ones before the first live one. The unique index
    makes two concurrent runs unreachable going forward, but a database written by an older build
    can still hold several, and stopping at the first live run would leave those sitting in
    ``RUNNING`` for ever — the index would then refuse every future sweep with no way out.

    Returns:
        The run still going, or None if none is. The newest, when a legacy database holds more
        than one, so the reason given for a refusal is the same on every call.
    """
    live: SweepRun | None = None
    runs = await SweepRun.find(SweepRun.state == SweepState.RUNNING).sort("-started_at").to_list()
    for run in runs:
        now = datetime.now(UTC)
        if now - run.started_at < STALE_AFTER:
            live = live or run
            continue
        await run.set(
            {
                "state": SweepState.ABANDONED,
                "finished_at": now,
                "error": (
                    "the process running this sweep stopped without finishing; "
                    f"it was last known to be running at {run.started_at.isoformat()}"
                ),
            }
        )
    return live


class SweepInProgress(Exception):
    """Raised when a sweep is asked for while one is already running.

    An exception rather than a ``None`` return, because every caller has to do something about it
    and a null would let one forget: the API turns it into a 409 and the scheduled task skips the
    pass. It carries the run so the refusal can say which sweep is in the way and since when.
    """

    def __init__(self, running: SweepRun | None) -> None:
        """Builds the refusal, naming the sweep in the way where one can still be identified.

        ``running`` is optional because the run that caused the refusal can finish between the
        insert being rejected and the message being built, and a refusal that cannot say which
        sweep is in the way is still a correct refusal.
        """
        started = (
            f" It started at {running.started_at.isoformat()}." if running is not None else ""
        )
        super().__init__(f"A sweep is already running.{started}")
        self.running = running


async def claim_run() -> SweepRun:
    """Claims the sole right to sweep and records that one has started, or refuses.

    Both ways of starting a sweep go through here, so the rule that only one runs at a time holds
    across them. An earlier version checked in the API only, which left the scheduled task free to
    start a second pass on top of a manual one — the exact overlap the check was written to stop.

    The refusal comes from the unique index rather than from the lookup above it. ``running_run``
    is called first to retire anything dead, because a stale run still occupies the index and would
    otherwise refuse every sweep after it; but its answer is not what decides, since two triggers
    arriving together both read "nothing running" before either inserts.

    Written before a single board is read, so a manual trigger can answer with a real run the
    instant it accepts the request instead of holding a connection open for the minutes a pass
    takes.

    Returns:
        The stored run, in its running state.

    Raises:
        SweepInProgress: If a sweep is already under way.
    """
    await running_run()
    try:
        return await SweepRun().insert()
    except DuplicateKeyError as error:
        raise SweepInProgress(await running_run()) from error


async def finish_run(run: SweepRun) -> SweepRun:
    """Sweeps every board and closes the given run with whatever happened.

    ``Exception`` is caught and filed on the run instead of escaping, because the two callers are a
    background task and a Celery task, and in both an exception that got out would be swallowed by
    a log nobody reads while the run sat in ``RUNNING`` until it went stale. Recording it as
    ``FAILED`` puts the reason where the person who asked for the sweep is already looking.

    ``BaseException`` is deliberately not caught, so a cancelled sweep still stops — and leaves the
    run running, which is precisely the state ``running_run`` later retires as abandoned.

    The closing write is guarded too, and for a reason worth stating: filing a failure is itself a
    database write, so the one failure most likely to have felled the sweep — the database being
    unreachable — is also the one that cannot be recorded. There is nowhere left to put the news at
    that point, so it is dropped and the run is left to be retired as ``ABANDONED`` an hour later.
    Letting it escape instead would only move an unwritable error into a log nobody reads, while
    leaving the run in exactly the same state.

    Args:
        run: The run this pass was started under.

    Returns:
        The same run, updated — in memory even if the closing write could not be made.
    """
    try:
        async with board_client() as client:
            summary = await sweep(client)
    except Exception as error:
        run.state = SweepState.FAILED
        run.error = f"{type(error).__name__}: {error}"
    else:
        run.state = SweepState.COMPLETED
        run.summary = summary
    run.finished_at = datetime.now(UTC)
    with suppress(Exception):
        await run.save()
    return run


async def _connected_sweep() -> SweepRun | None:
    """Opens a database connection, claims a run, sweeps, and closes the connection again.

    Separate from ``sweep`` so that neither the scheduled path nor a test has to own what the
    other does: this opens a connection because Celery hands it a bare process, while a test drives
    ``sweep`` directly against a database its fixture already opened.

    Claims through ``claim_run`` rather than inserting a run outright, so the scheduled sweep is
    refused while a manual one is in progress. Beat firing on top of a dashboard-triggered pass
    would otherwise put two reconciles over the same postings, each reading the other's writes as
    board state.

    Returns:
        The recorded run, or None if a sweep was already running and this pass was skipped.
    """
    db_client = await init_db()
    try:
        run = await claim_run()
    except SweepInProgress:
        return None
    else:
        return await finish_run(run)
    finally:
        await db_client.close()


def run_sweep() -> SweepRun | None:
    """Runs one complete sweep from synchronous code.

    ``asyncio.run`` per sweep, rather than a loop kept alive between tasks: the Mongo client and
    its pools are bound to the loop that created them, and Celery forks by default, so a cached
    client would be inherited into children that must not share it. At one sweep every six hours
    the setup cost is irrelevant.

    Returns:
        The recorded run, so the scheduled path leaves the same history a manual one does, or
        None if a sweep was already running and this one was skipped.
    """
    return asyncio.run(_connected_sweep())


def main() -> None:
    """Runs one sweep on demand and prints the run it recorded.

    Reached with ``python -m app.sweep``, so a reader with no Redis and no worker can still see
    the thing work. Says so plainly when the sweep was skipped, since a bare ``null`` would read
    as the sweep having found nothing rather than never having started.
    """
    run = run_sweep()
    if run is None:
        print("A sweep is already running; this one was skipped.")
        return
    print(run.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
