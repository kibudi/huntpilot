"""Shared test fixtures, and the one application every test file starts from.

Beanie has no in-memory backend: ``init_beanie`` must run against a real server before a Document
can even be constructed. Tests therefore need a live MongoDB and run against a throwaway database,
never the configured one.

Because ``init_beanie`` binds the Document classes process-globally, tests cannot be isolated by
scoping a connection per test the way a SQLAlchemy session would be. Isolation comes from dropping
the collections before each test instead, and the suite must not run in parallel.
"""

from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from pymongo import AsyncMongoClient

from app.config import settings
from app.db import init_db
from app.main import app
from app.profile import Profile

TEST_DB = "huntpilot_test"

PAYLOAD = {
    "company": "Gong",
    "role": "Backend Engineer",
    "location": "Remote (IL)",
    "source": "LinkedIn",
    "url": "https://example.com/jobs/1",
}
"""One valid application: exactly the fields with no default, and nothing a client may not send.

Shared because every application test needs the same thing and each file used to carry its own
copy, which meant a new required field had to be added in as many places or the rest would start
failing for a reason none of them is about. It doubles as document keyword arguments, since the
fields a client must supply are the same ones the document has no default for.

Tests that care about one field override it at the call site rather than editing this.
"""


@pytest.fixture
def berlin_profile() -> Profile:
    """A search with nothing in common with the committed profile: Go, in Berlin, five years in.

    Every value is deliberately the opposite of the default's. It looks at German cities instead
    of Israeli ones; its families are named for a stack this repository's owner does not work in,
    including one — "distributed systems" — that the fixed set of families used to make
    unsayable; Python and React are on its *unknown* side; it tolerates "Senior" in a title,
    because five years in that is what the person searching is; and it accepts a weaker match at
    0.6. A posting the committed profile keeps is one this profile must throw away, and the
    reverse.

    Lives here rather than in one test file because the relevance and the stack tests both need
    it to make the same point, and two copies would drift into proving two different things.
    """
    return Profile.model_validate(
        {
            "local_fragments": ["Berlin", "germany", "münchen", "munich", "hamburg"],
            "remote_fragments": ["remote", "anywhere"],
            "seniority_markers": ["principal", "staff", "head of", "director", "vp", "chief"],
            "role_families": {
                "backend": [
                    "back end",
                    "back-end",
                    "backend",
                    "go developer",
                    "go engineer",
                    "golang developer",
                    "golang engineer",
                ],
                "distributed systems": ["distributed systems"],
            },
            "known": {
                "go": ["golang", "go developer", "go engineer", "go programming"],
                "grpc": ["grpc"],
                "kubernetes": ["kubernetes", "k8s"],
                "postgresql": ["postgresql", "postgres"],
            },
            "unknown": {
                "python": ["python"],
                "fastapi": ["fastapi"],
                "react": ["react"],
                "java": ["java"],
            },
            "min_tech_score": 0.6,
            "max_years": 5,
        }
    )


@pytest.fixture
async def db() -> AsyncIterator[AsyncMongoClient[dict[str, Any]]]:
    """Connects to the throwaway test database and leaves it empty for the test.

    Isolation comes from dropping the collections *before* each test, never from dropping the
    database after one. A drop is acknowledged before the server has finished it, so against a
    remote cluster the drop issued for one test can still be landing while the next has begun
    inserting — deleting that test's data underneath it. It surfaced as documents that a count
    could see and a query could not, in whichever test happened to be running when the drop caught
    up, which is why it looked like an unrelated regression.

    The emptying happens before ``init_beanie`` rather than after it, which is not a detail.
    ``init_beanie`` builds the indexes, one of which is unique on the running sweep, and a unique
    index cannot be built over a collection that already holds two of them. A test that failed
    part-way and left two running runs behind would otherwise poison every later run of the whole
    suite at fixture setup, with an error naming an index rather than the test that caused it.

    Collections are dropped rather than emptied, so an index left renamed or removed by a test is
    rebuilt from the models instead of persisting into the next one.
    """
    client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(
        settings.mongodb_uri, tz_aware=True
    )
    for name in await client[TEST_DB].list_collection_names():
        await client[TEST_DB][name].drop()
    await client.close()

    client = await init_db(db_name=TEST_DB)
    try:
        yield client
    finally:
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


async def create(api: AsyncClient, **overrides: Any) -> dict[str, Any]:
    """Creates one application over the API and returns the response body.

    For the tests whose subject is what happens *after* a document exists. Tests about the create
    endpoint itself post explicitly instead, since going through a helper would hide the request
    they are making assertions about.

    Args:
        api: The client bound to the app.
        **overrides: Fields to change on ``PAYLOAD`` before posting it.

    Returns:
        The created application as the API returned it.
    """
    response = await api.post("/api/applications", json=PAYLOAD | overrides)
    body: dict[str, Any] = response.json()
    return body
