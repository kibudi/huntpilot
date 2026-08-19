"""Reading every watched board in one pass, on a schedule and by hand.

This is the loop the rest of the board tracker was written for. ``fetch_board``, ``relevant`` and
``reconcile`` each do one thing to one board; nothing until now put them in order or ran them over
the watchlist, so every sweep so far has been a throwaway script.

One HTTP client serves the whole pass. Each board is a separate host, but the client also carries
the timeout and redirect policy, and building one per company would scatter that policy across
however many companies happen to be watched.

Boards are read one after another rather than concurrently. A sweep runs every six hours against a
few dozen public APIs, so nothing is waiting on it, and a serial pass keeps the failure of one
board a local event instead of one branch of a gather that has to be unpicked afterwards.

The failure rule matters more than anything else here. Closure is inferred from absence — a board
that stops listing a posting is how this system learns the role is gone — so a board that could
not be read must produce *no* reconcile at all. Handing ``reconcile`` an empty list because a
fetch failed would report every one of that company's open roles as heading for closed, and two
such sweeps would close them outright. That is why the failure path below records and continues
without touching storage, and why the fetch and the reconcile sit in one ``try`` rather than the
fetch alone: anything that can go wrong before a board reading is known-good has to land in the
same place.
"""

import asyncio

import httpx
from pydantic import BaseModel, Field

from app.boards import fetch_board, reconcile
from app.db import init_db
from app.models import ATS, Company
from app.relevance import relevant

BOARD_TIMEOUT = httpx.Timeout(20.0)
"""How long any single board request may take.

Longer than httpx's five-second default because these responses carry every posting's full body,
which on the larger boards is megabytes. The default turns those boards into timeouts, and a
timeout here is indistinguishable from a board that could not be read at all.
"""


class BoardFailure(BaseModel):
    """One board that could not be read during a sweep, and why.

    The company is identified by ATS and token as well as by name, because the name is only a
    label while that pair is what addresses the board — it is the pair to check when a failure
    turns out to be a wrong token rather than an outage.
    """

    name: str
    ats: ATS
    token: str
    error: str


class SweepSummary(BaseModel):
    """What one pass over the whole watchlist did.

    The posting counts are ``SweepResult`` totalled across the boards that were actually read.
    They are reported alongside ``boards_failed`` rather than on their own for a reason: a sweep
    where half the boards failed produces small, honest-looking counts, and only the failure count
    says that the sweep saw half the market.
    """

    boards_swept: int = 0
    boards_failed: int = 0
    added: int = 0
    still_open: int = 0
    closed: int = 0
    reopened: int = 0
    failures: list[BoardFailure] = Field(default_factory=list)


async def sweep(client: httpx.AsyncClient) -> SweepSummary:
    """Reads every watched board, stores what is worth storing, and reports what changed.

    A board that raises for any reason — a wrong token answering 404, an outage, a timeout, a
    payload that does not have the shape its system documents — is counted as a failure and the
    pass moves to the next company. ``Exception`` is caught rather than the HTTP errors alone
    because the aim is that no single company can end the sweep, and the ways a board can
    disappoint are not confined to one library. ``BaseException`` is deliberately not caught, so a
    cancelled sweep still stops.

    The client is passed in rather than opened here so that one pass shares one connection pool,
    and so tests can hand in a transport instead of reaching the network.

    Args:
        client: An HTTP client to read every board with.

    Returns:
        Totals across the boards that answered, plus a record of the ones that did not.
    """
    summary = SweepSummary()

    for company in await Company.find_all().to_list():
        try:
            postings = await fetch_board(company, client)
            result = await reconcile(company, relevant(postings))
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


async def _connected_sweep() -> SweepSummary:
    """Opens everything one sweep needs, sweeps, and closes it again.

    Separate from ``sweep`` so that the loop itself owns no connections: tests drive ``sweep``
    against a database a fixture already opened, while the scheduled and manual entry points come
    through here and get a connection of their own.
    """
    db_client = await init_db()
    try:
        async with httpx.AsyncClient(timeout=BOARD_TIMEOUT, follow_redirects=True) as client:
            return await sweep(client)
    finally:
        await db_client.close()


def run_sweep() -> SweepSummary:
    """Runs one complete sweep from synchronous code.

    Celery tasks are ordinary synchronous functions and the sweep is async, so something has to
    bridge the two. ``asyncio.run`` per sweep is that bridge, in preference to keeping a loop alive
    between tasks: the Mongo client and the connection pools underneath it are bound to the loop
    they were created on, so a client cached across tasks would be reused from a loop it does not
    belong to, and a worker that forks — which is Celery's default — would inherit that loop into
    children that must not share it. Opening and closing everything inside one ``asyncio.run``
    makes each sweep self-contained, and at one sweep every six hours the setup cost is not worth a
    thought.

    Returns:
        What the sweep did.
    """
    return asyncio.run(_connected_sweep())


def main() -> None:
    """Runs one sweep on demand and prints the summary.

    The manual counterpart to the scheduled task, reached with ``python -m app.sweep``. It exists
    because a reader with no Redis and no worker running still needs a way to see the thing work,
    and because a sweep is the obvious first thing to reach for when the stored postings look
    wrong.
    """
    print(run_sweep().model_dump_json(indent=2))


if __name__ == "__main__":
    main()
