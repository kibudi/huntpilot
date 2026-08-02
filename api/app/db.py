"""MongoDB connection and Beanie initialisation.

Every service that touches the database — the API, the Celery worker, the Discord bot, scripts and
tests — calls ``init_db()`` once at startup.

``init_beanie`` binds the Document classes process-globally, so afterwards models are used directly
(``Application.find_all()``) with no connection or session to pass around. That is why there is no
per-request dependency here as there would be with a SQLAlchemy session.
"""

from typing import Any

from beanie import init_beanie
from pymongo import AsyncMongoClient

from app.config import settings
from app.models import Application

DOCUMENT_MODELS = [Application]


async def init_db(
    uri: str | None = None,
    db_name: str | None = None,
) -> AsyncMongoClient[dict[str, Any]]:
    """Connects to MongoDB and registers the document models.

    ``tz_aware`` is required, not optional: BSON stores no offset, so without it every datetime
    read back is naive. Serialised to JSON that produces a timestamp with no ``Z``, which a client
    in any non-UTC zone reads as local time — an application saved seconds ago appears hours old.

    The client is closed explicitly if registration fails, because the caller has no reference to
    close in that case and the connection would otherwise be left open.

    Args:
        uri: Connection string; defaults to the configured ``MONGODB_URI``.
        db_name: Database name; defaults to the configured ``MONGODB_DB``. Tests pass a throwaway
            name so they never touch real data.

    Returns:
        The connected client, so the caller can close it on shutdown.
    """
    client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(
        uri or settings.mongodb_uri,
        tz_aware=True,
    )
    try:
        await init_beanie(
            database=client[db_name or settings.mongodb_db],
            document_models=DOCUMENT_MODELS,
        )
    except BaseException:
        await client.close()
        raise
    return client
