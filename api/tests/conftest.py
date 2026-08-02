"""Shared test fixtures.

Beanie has no in-memory backend: ``init_beanie`` must run against a real server before a Document
can even be constructed. Tests therefore need a live MongoDB and run against a throwaway database,
never the configured one.

Because ``init_beanie`` binds the Document classes process-globally, tests cannot be isolated by
scoping a connection per test the way a SQLAlchemy session would be. Isolation comes from emptying
the collections before each test instead, and the suite must not run in parallel.
"""

from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from pymongo import AsyncMongoClient

from app.db import DOCUMENT_MODELS, init_db
from app.main import app

TEST_DB = "huntpilot_test"


@pytest.fixture
async def db() -> AsyncIterator[AsyncMongoClient[dict[str, Any]]]:
    """Connects to the throwaway test database and leaves it empty for the test.

    The database is dropped afterwards so a failed run leaves nothing behind.
    """
    client = await init_db(db_name=TEST_DB)
    try:
        for model in DOCUMENT_MODELS:
            await model.get_pymongo_collection().delete_many({})
        yield client
    finally:
        await client.drop_database(TEST_DB)
        await client.close()


@pytest.fixture
async def api(db: AsyncMongoClient[dict[str, Any]]) -> AsyncIterator[AsyncClient]:
    """Yields an HTTP client bound to the app in-process.

    The app's lifespan is deliberately not run: it would call ``init_db()`` with the configured
    settings and point the tests at the real database. The ``db`` fixture has already initialised
    Beanie against the test database, and that binding is what the routes use.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
