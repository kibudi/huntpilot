"""FastAPI application for huntpilot."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from http import HTTPStatus

from beanie import PydanticObjectId
from fastapi import FastAPI, HTTPException
from pymongo.errors import DuplicateKeyError

from app.db import init_db
from app.models import Application
from app.schemas import ApplicationCreate, ApplicationRead, ApplicationUpdate


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Holds one MongoDB connection open for the lifetime of the application.

    Connecting per request would pay the Atlas TLS handshake every time; the driver maintains its
    own pool, so a single client shared across requests is the intended usage.
    """
    client = await init_db()
    try:
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
