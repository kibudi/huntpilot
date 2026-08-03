"""FastAPI application for huntpilot."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from http import HTTPStatus

from beanie import PydanticObjectId
from fastapi import FastAPI, HTTPException

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

    Raises:
        HTTPException: 404 if the document cannot be read back, which should not occur.
    """
    now = datetime.now(UTC)
    document = await Application(**payload.model_dump(), created_at=now, updated_at=now).insert()
    stored = await Application.get(document.id)
    if stored is None:
        raise HTTPException(HTTPStatus.NOT_FOUND, "Application disappeared after creation")
    return ApplicationRead.model_validate(stored)


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

    Raises:
        HTTPException: 404 if no application has this identifier.
    """
    changes = payload.model_dump(exclude_unset=True)
    document = await Application.get(application_id)
    if document is None:
        raise HTTPException(HTTPStatus.NOT_FOUND, "Application not found")

    if changes:
        await document.set({**changes, "updated_at": datetime.now(UTC)})
        refreshed = await Application.get(application_id)
        if refreshed is None:
            raise HTTPException(HTTPStatus.NOT_FOUND, "Application disappeared during update")
        document = refreshed

    return ApplicationRead.model_validate(document)
