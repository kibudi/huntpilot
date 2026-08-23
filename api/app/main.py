"""FastAPI application for huntpilot."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from http import HTTPStatus

from beanie import PydanticObjectId
from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError as PydanticValidationError
from pymongo.errors import DuplicateKeyError

from app.db import init_db
from app.models import Application, Company, Posting, PostingStatus, SweepRun
from app.profile import Profile, ProfileError, active_profile, store_profile
from app.relevance import region
from app.schemas import (
    ApplicationCreate,
    ApplicationRead,
    ApplicationUpdate,
    PostingRead,
    ProfileBody,
    SweepRunRead,
)
from app.sweep import SweepInProgress, claim_run, finish_run


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Holds one MongoDB connection open for the lifetime of the application, and seeds the profile.

    Connecting per request would pay the Atlas TLS handshake every time; the driver maintains its
    own pool, so a single client shared across requests is the intended usage.

    Seeding here means a fresh database has a profile before the first request rather than as a
    side effect of one, and that a stored profile which no longer validates stops the application
    at startup with the reason — the same guarantee the committed file has always had, now that the
    file is no longer what gets filtered with.
    """
    client = await init_db()
    try:
        await active_profile()
        yield
    finally:
        await client.close()


app = FastAPI(title="huntpilot", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    """Reports that the process is up. Does not check the database."""
    return {"status": "ok"}


@app.get("/api/applications")
async def list_applications() -> list[ApplicationRead]:
    """Returns every tracked application, most recently updated first.

    Documents are converted to the response schema explicitly rather than returned raw, so the
    JSON and the OpenAPI description both describe the wire format instead of the stored one.

    The sort key is given as a string rather than ``-Application.updated_at`` because the operator
    form is not expressible in the type system: the attribute is annotated ``datetime``, which has
    no unary minus.
    """
    documents = await Application.find_all().sort("-updated_at").to_list()
    return [ApplicationRead.model_validate(document) for document in documents]


@app.get("/api/postings")
async def list_postings(status: PostingStatus | None = None) -> list[PostingRead]:
    """Returns postings swept from company boards, most recently discovered first.

    The sort key is ``first_seen_at`` rather than ``last_seen_at`` because this list answers "what
    has appeared", and every successful sweep bumps ``last_seen_at`` on every posting still listed
    — sorting on it would reshuffle the whole list after each sweep and bury a genuinely new
    opening under roles that have been up for months.

    Omitting ``status`` returns open and closed postings together, since a closed posting is the
    result the tracker exists to produce and hiding it by default would make the feature look
    empty.

    Company display names are read in one query and matched in Python. Looking each one up per
    posting would issue a query per row, which grows with the board's size for data that repeats
    once per company. The watchlist is the small side of that join, so reading it whole costs one
    round trip regardless of how many postings come back.

    A posting whose company is no longer on the watchlist falls back to its token as the display
    name. This is a real state, not a corruption: removing a company stops its board being swept
    but leaves the postings already recorded, and dropping or failing on those would delete
    history the user can no longer recover.

    ``region`` is classified here rather than stored, so that correcting the profile's list of
    local spellings takes effect on every posting already swept instead of only on those swept
    afterwards. The profile is read per request for the same reason: a city added through
    ``PUT /api/profile`` reclassifies the whole list on the next refresh, with no sweep and no
    restart in between.

    Args:
        status: Restricts the list to open or to closed postings; both are returned if omitted.

    Returns:
        The matching postings, newest discovery first.

    Raises:
        HTTPException: 422 with the reason, if the stored profile no longer validates. Reading a
            profile is not this endpoint's purpose, but it needs one to classify a region, and the
            same reasoning as ``read_profile`` applies: a 500 would put "which entry is empty" in a
            server log and leave the board tab with a failure nobody can act on.
    """
    query = Posting.find_all() if status is None else Posting.find(Posting.status == status)
    postings = await query.sort("-first_seen_at").to_list()
    companies = await Company.find_all().to_list()
    try:
        profile = await active_profile()
    except ProfileError as error:
        raise HTTPException(HTTPStatus.UNPROCESSABLE_ENTITY, str(error)) from error
    names = {(company.ats, company.token): company.name for company in companies}
    return [
        PostingRead(
            id=str(posting.id),
            company=names.get((posting.ats, posting.company_token), posting.company_token),
            ats=posting.ats,
            title=posting.title,
            location=posting.location_raw,
            region=region(posting.location_raw, profile),
            url=posting.url,
            status=posting.status,
            first_seen_at=posting.first_seen_at,
            last_seen_at=posting.last_seen_at,
            closed_at=posting.closed_at,
        )
        for posting in postings
    ]


@app.post("/api/applications", status_code=HTTPStatus.CREATED)
async def create_application(payload: ApplicationCreate) -> ApplicationRead:
    """Tracks a new application and returns it as stored.

    The document is re-read before being returned rather than serialised from memory. BSON stores
    milliseconds while Python holds microseconds, so the in-memory object does not match what a
    later read will produce, and a client comparing the two would see them differ.

    Both timestamps are set from one instant rather than left to their separate defaults, so a
    never-modified document satisfies ``created_at == updated_at``. Two independent calls can fall
    either side of a millisecond boundary and break that.

    A posting link already tracked is a 409. The check is left to the unique index rather than a
    lookup before the insert: a lookup and an insert are two operations, and two requests arriving
    together both pass the lookup before either writes. Blank links are exempt, since a job from
    an agency or an undisclosed employer has none.

    Raises:
        HTTPException: 409 if another application already has this url.
        HTTPException: 404 if the document cannot be read back, which should not occur.
    """
    now = datetime.now(UTC)
    try:
        document = await Application(
            **payload.model_dump(), created_at=now, updated_at=now
        ).insert()
    except DuplicateKeyError as error:
        raise HTTPException(
            HTTPStatus.CONFLICT, "An application with this url is already tracked"
        ) from error
    stored = await Application.get(document.id)
    if stored is None:
        raise HTTPException(HTTPStatus.NOT_FOUND, "Application disappeared after creation")
    return ApplicationRead.model_validate(stored)


@app.delete("/api/applications/{application_id}", status_code=HTTPStatus.NO_CONTENT)
async def delete_application(application_id: PydanticObjectId) -> None:
    """Removes one application permanently.

    The deletion is issued as a single conditional operation rather than a read followed by a
    delete, and ``deleted_count`` is what distinguishes a hit from a miss. The read-then-delete
    form has a window in which a concurrent request removes the document in between, which would
    report success for a delete that did nothing.

    A repeat call is a 404 rather than another 204. The alternative — treating every delete as
    successful — would hide a wrong identifier, and this is the one endpoint whose mistakes cannot
    be undone.

    Nothing is returned: 204 forbids a body, and echoing a document the server has just destroyed
    would invite a client to keep using it.

    Raises:
        HTTPException: 404 if no application has this identifier.
    """
    result = await Application.find_one(Application.id == application_id).delete()
    if result is None or result.deleted_count == 0:
        raise HTTPException(HTTPStatus.NOT_FOUND, "Application not found")


@app.patch("/api/applications/{application_id}")
async def update_application(
    application_id: PydanticObjectId, payload: ApplicationUpdate
) -> ApplicationRead:
    """Applies changes to one application and returns it as stored.

    Only fields present in the request body are written, so omitting a field leaves it alone.
    ``updated_at`` is bumped here because MongoDB has no on-update mechanism and Beanie does not
    supply one; a write that skipped this would leave the sort order and the bot's staleness
    checks wrong.

    An empty body is accepted and changes nothing, including ``updated_at`` — nothing was
    modified, so claiming otherwise would be a lie the dashboard sorts on.

    Moving ``url`` onto a link another application already holds is a 409, for the same reason the
    create endpoint refuses one: it would turn two records into duplicates through the back door.

    Raises:
        HTTPException: 404 if no application has this identifier.
        HTTPException: 409 if the new url is already tracked by another application.
    """
    changes = payload.model_dump(exclude_unset=True)
    document = await Application.get(application_id)
    if document is None:
        raise HTTPException(HTTPStatus.NOT_FOUND, "Application not found")

    if changes:
        try:
            await document.set({**changes, "updated_at": datetime.now(UTC)})
        except DuplicateKeyError as error:
            raise HTTPException(
                HTTPStatus.CONFLICT, "An application with this url is already tracked"
            ) from error
        refreshed = await Application.get(application_id)
        if refreshed is None:
            raise HTTPException(HTTPStatus.NOT_FOUND, "Application disappeared during update")
        document = refreshed

    return ApplicationRead.model_validate(document)


def _as_body(profile: Profile) -> ProfileBody:
    """Converts a validated profile into the shape the API publishes it as.

    Both profile endpoints answer with the stored profile, so the conversion lives in one place
    rather than being written twice and drifting when a field is added.

    ``mode="json"`` is doing real work rather than being a habit: a ``Profile`` holds compiled
    ``re.Pattern`` objects, and only the JSON dump runs the serialiser that turns each one back
    into the pattern string a client sent and can send again.
    """
    return ProfileBody.model_validate(profile.model_dump(mode="json"))


@app.get("/api/profile")
async def read_profile() -> ProfileBody:
    """Returns the search every sweep is currently run against.

    Never a 404. A database that has never been swept still has a profile, because the committed
    file seeds one on first read — and a dashboard whose editor could not load until something had
    written a profile would have no way to write the first one.

    Returned through ``Profile`` rather than straight from storage, so what a client sees is the
    normalised search the filters will actually use: fragments lower-cased, an omitted ``unknown``
    filled in.

    Raises:
        HTTPException: 422 with the reason, if what is stored no longer validates. That is not a
            client error, but it is the only reply that carries the reason to the one screen that
            can fix it; a 500 would put "which pattern is broken" in a server log and leave the
            editor with a blank failure it cannot act on.
    """
    try:
        return _as_body(await active_profile())
    except ProfileError as error:
        raise HTTPException(HTTPStatus.UNPROCESSABLE_ENTITY, str(error)) from error


@app.put("/api/profile")
async def replace_profile(payload: ProfileBody) -> ProfileBody:
    """Replaces the stored search profile and returns it as stored.

    A replacement rather than a patch, because the fields are not independent: which families are
    tried in which order, and which technologies count as known against which count as unknown,
    only mean anything as a set. Sending the whole profile is also what the dashboard's editor
    naturally does, since it was filled from ``GET`` in the first place.

    Validation is ``Profile``'s, not this schema's. The body only has to be the right shape to get
    here; whether it is a search worth running — every pattern compiling, at least one family, at
    least one known technology, somewhere in scope, a score that is a share rather than a
    percentage — is decided by the same model the committed file has always been held to, and its
    complaint is passed through verbatim. Each of those failures produces a sweep that stores
    nothing while looking perfectly healthy, which is why they are refusals rather than defaults.

    The response is the stored profile rather than an echo of the request, so a client sees the
    normalisation that was applied to what it sent.

    Raises:
        HTTPException: 422 with the reason, if the profile would not filter anything usefully. The
            detail is ``ValidationError.errors()`` rather than the exception's text, so that it is
            the same list of ``loc``/``msg`` entries FastAPI itself returns when the *shape* is
            wrong. An editor can point at the offending field either way; two formats would mean it
            could only do so for half the refusals.
    """
    try:
        replacement = Profile.model_validate(payload.model_dump())
    except PydanticValidationError as error:
        raise HTTPException(
            HTTPStatus.UNPROCESSABLE_ENTITY, jsonable_encoder(error.errors())
        ) from error

    await store_profile(replacement)
    return _as_body(replacement)


_sweeps_in_flight: set[asyncio.Task[SweepRun]] = set()
"""Strong references to the sweeps currently running in this process.

The event loop holds only a weak reference to a running task, so a task nobody keeps can be
garbage-collected mid-await and stop without a trace — a sweep that silently ends part-way through
the watchlist, leaving its run to be retired as abandoned an hour later. Each task removes itself
when it finishes, so this never grows.
"""


@app.post("/api/sweeps", status_code=HTTPStatus.ACCEPTED)
async def start_sweep() -> SweepRunRead:
    """Starts one sweep of the watchlist and returns the run it was recorded as, immediately.

    A sweep reads a few dozen boards serially and takes minutes, so it cannot happen inside the
    request: a client would sit on an open connection past every sensible timeout for a result it
    could instead poll ``GET /api/sweeps`` for. The run is created before the response so there is
    something to poll from the first moment, which is why it comes back in the ``running`` state
    with no summary. ``202`` rather than ``201`` for the same reason — what this accepts is work,
    and the run it names is a receipt for work not yet done.

    Started with ``asyncio.create_task`` rather than as a FastAPI background task, because
    Starlette awaits background tasks *inside* the response cycle: the body is flushed but the
    connection is not released until they finish. A client polling ``GET /api/sweeps`` over the
    same keep-alive connection would block for the whole sweep — the precise thing this endpoint
    returns early to avoid. A task detaches from the request instead.

    Run in this process rather than queued to Celery. Celery is the right home for the *scheduled*
    sweep — it is what Beat drives, and it survives the API restarting — but making a button in the
    dashboard depend on it would mean the feature silently does nothing whenever Redis or the
    worker is not up, which for a project that has to run on one laptop is most of the time. The
    honest cost is that a sweep started this way dies with the API: an interrupted run is left in
    ``running`` and is retired as ``abandoned`` by the next attempt, rather than being retried.

    Raises:
        HTTPException: 409, naming when the running sweep started, if one already is. Two passes at
            once would interleave their reconciles over the same postings, and the second would see
            the first's writes as board state. The refusal is the database's — see ``claim_run``.
    """
    try:
        run = await claim_run()
    except SweepInProgress as error:
        raise HTTPException(HTTPStatus.CONFLICT, str(error)) from error

    task = asyncio.create_task(finish_run(run))
    _sweeps_in_flight.add(task)
    task.add_done_callback(_sweeps_in_flight.discard)
    return SweepRunRead.model_validate(run)


@app.get("/api/sweeps")
async def list_sweeps() -> list[SweepRunRead]:
    """Returns every recorded sweep, most recently started first.

    Sorted on ``started_at`` rather than ``finished_at`` because the run a client is most likely to
    want is the one happening right now, which has not finished — and because a null sorts nowhere
    useful.

    Unpaginated. Sweeps run four times a day, so the whole history is a few hundred small documents
    a year, and a limit would have to be either a guess at what "recent" means or a parameter
    nothing yet needs.
    """
    runs = await SweepRun.find_all().sort("-started_at").to_list()
    return [SweepRunRead.model_validate(run) for run in runs]
