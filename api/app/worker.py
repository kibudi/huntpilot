"""The Celery application and the scheduled sweep task.

Lives inside the ``app`` package rather than in a service tree of its own. There is one task, and
it is one call into ``app.sweep``; a separate package would have to depend on this one anyway, and
would duplicate the dependency set and the image to do it. The worker and the beat scheduler run
as extra compose services built from the same image as the API, differing only in their command.

The worker is a second process against the same database rather than a client of the API. That is
allowed by the rule that ``api/`` owns the database because this *is* ``api/`` — same package, same
models, same ``init_db``.

Beat is a separate process from the worker on purpose. Running the scheduler inside a worker
(``celery worker --beat``) is documented as development-only, and two workers each with an embedded
scheduler would each fire the sweep.

Celery ships no type information, so its task decorator is untyped and strict mypy rejects what it
returns. The suppression is on the decorator itself and narrowed to that one error code, which
leaves every other check on the task in force.

The schedule is configured in UTC, matching the timestamps every document is written with. A
schedule on local time would shift twice a year against data that never does, and would move the
sweep interval by an hour on the days that happens.
"""

from datetime import timedelta

from celery import Celery

from app.config import settings
from app.sweep import SweepSummary, run_sweep

SWEEP_INTERVAL = timedelta(hours=6)
"""How often the watchlist is swept.

Boards change over days, not minutes, so six hours is well inside the resolution anyone reads this
data at. It also keeps a posting's closure — which needs two consecutive misses — confirmed within
half a day rather than a week, and holds the request count against these unauthenticated public
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

    The body is deliberately one call. ``run_sweep`` owns the bridge from Celery's synchronous
    world into the async sweep and explains it, which keeps that reasoning in one place instead of
    being re-derived by every future caller — and keeps the task itself something a person can run
    without Celery.

    A failing board does not fail the task: the sweep records it and carries on, so the task result
    is a report rather than a raised exception. The task retries nothing for the same reason —
    absence is evidence in this system, and an immediate retry of a whole sweep would rewrite
    timestamps for the boards that already answered.

    Returns:
        The ``SweepSummary`` as plain data, because a task result is serialised to JSON and Celery
        has no way to reconstruct a Pydantic model from it.
    """
    summary: SweepSummary = run_sweep()
    return summary.model_dump(mode="json")
