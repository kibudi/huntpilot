"""The Celery application and the scheduled sweep task.

Lives inside the ``app`` package rather than a service tree of its own: there is one task, it is
one call into ``app.sweep``, and a separate package would duplicate the dependency set and the
image to do it. The worker and beat run as extra compose services from the same image, differing
only in their command — so the worker is still ``api/``, which is what owns the database.

Beat is a separate process from the worker on purpose. An embedded scheduler is documented as
development-only, and two workers with one each would both fire the sweep.

The schedule is UTC, matching the timestamps every document is written with; a local-time schedule
would shift twice a year against data that never does.
"""

from datetime import timedelta

from celery import Celery

from app.config import settings
from app.sweep import SweepSummary, run_sweep

SWEEP_INTERVAL = timedelta(hours=6)
"""How often the watchlist is swept.

Boards change over days, not minutes. Six hours confirms a closure — which needs two consecutive
misses — within half a day, while keeping the request count against these unauthenticated public
APIs to a few hundred a day.
"""

celery_app = Celery("huntpilot", broker=settings.redis_url, backend=settings.redis_url)

celery_app.conf.update(
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        "sweep-boards": {
            "task": "app.sweep_boards",
            "schedule": SWEEP_INTERVAL,
        }
    },
)


@celery_app.task(name="app.sweep_boards")  # type: ignore[untyped-decorator]
def sweep_boards() -> dict[str, object]:
    """Sweeps every watched board, and is the only thing Beat is scheduled to run.

    Nothing is retried. Absence is evidence in this system, so re-running a whole sweep would
    rewrite timestamps for the boards that already answered. A failing board is reported in the
    result rather than raised.

    Returns:
        The ``SweepSummary`` as plain data — a task result is serialised to JSON, and Celery
        cannot reconstruct a Pydantic model from it.
    """
    summary: SweepSummary = run_sweep()
    return summary.model_dump(mode="json")
