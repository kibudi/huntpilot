"""Reading every watched board in one pass, on a schedule and by hand.

Boards are read serially, sharing one client. A sweep runs every six hours against a few dozen
public APIs, so nothing is waiting on it, and a serial pass keeps one board's failure local.

The failure rule matters more than anything else here. Closure is inferred from absence, so a
board that could not be read must produce *no* reconcile at all — handing ``reconcile`` an empty
list after a failed fetch would report every one of that company's roles as heading for closed.
Hence the fetch and the reconcile share one ``try``: anything that can go wrong before a board
reading is known-good has to land in the same place.
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

    ``Exception`` is caught rather than the HTTP errors alone, because no single company may end
    the sweep and the ways a board can disappoint are not confined to one library.
    ``BaseException`` is deliberately not caught, so a cancelled sweep still stops.

    Args:
        client: An HTTP client to read every board with, shared across the pass.

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

    Separate from ``sweep`` so the loop owns no connections: tests drive ``sweep`` against a
    database a fixture already opened.
    """
    db_client = await init_db()
    try:
        async with httpx.AsyncClient(timeout=BOARD_TIMEOUT, follow_redirects=True) as client:
            return await sweep(client)
    finally:
        await db_client.close()


def run_sweep() -> SweepSummary:
    """Runs one complete sweep from synchronous code.

    ``asyncio.run`` per sweep, rather than a loop kept alive between tasks: the Mongo client and
    its pools are bound to the loop that created them, and Celery forks by default, so a cached
    client would be inherited into children that must not share it. At one sweep every six hours
    the setup cost is irrelevant.

    Returns:
        What the sweep did.
    """
    return asyncio.run(_connected_sweep())


def main() -> None:
    """Runs one sweep on demand and prints the summary.

    Reached with ``python -m app.sweep``, so a reader with no Redis and no worker can still see
    the thing work.
    """
    print(run_sweep().model_dump_json(indent=2))


if __name__ == "__main__":
    main()
