"""FastAPI application for huntpilot."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from http import HTTPStatus

from fastapi import FastAPI

from app.db import init_db
from app.models import Application
from app.schemas import ApplicationCreate, ApplicationRead


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

    The stored document is returned rather than the payload, so the caller receives the server's
    identifier and timestamps without having to re-read.
    """
    document = await Application(**payload.model_dump()).insert()
    return ApplicationRead.model_validate(document)
