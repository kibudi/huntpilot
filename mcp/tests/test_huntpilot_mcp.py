"""Tests for the huntpilot MCP server.

The API is replaced with an ``httpx.MockTransport`` so the suite needs neither a running
backend nor a database.

The tools build their own client, so a test of a tool rather than of its helper patches
``httpx.AsyncClient``. That patch is what makes "rejected before any request" a claim the suite
can check: without it, a validation bug would send a real request to whatever is listening on
port 8000, which on a development machine is the developer's own huntpilot.
"""

import json
from typing import Any

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from huntpilot_mcp import (
    API_BASE_URL,
    fetch_applications,
    list_applications,
    log_application,
    patch_status,
    post_application,
    update_status,
)

APPLICATIONS = [
    {"id": "1", "company": "Wix", "role": "Backend", "status": "applied"},
    {"id": "2", "company": "Monday", "role": "FDE", "status": "saved"},
    {"id": "3", "company": "Gong", "role": "AI Builder", "status": "applied"},
]

JOB = {
    "company": "Kaltura",
    "role": "Implementation Specialist",
    "location": "Tel Aviv",
    "source": "LinkedIn",
    "url": "https://example.com/jobs/1",
}

MISSING_ID = "0" * 24
"""A well-formed ObjectId that no application holds, which the API answers with 404.

Spelled out because the distinction matters: an id of the wrong shape never reaches the
handler, so it cannot produce a 404.
"""


def recording_client(
    status_code: int,
    body: Any = None,
) -> tuple[httpx.AsyncClient, list[httpx.Request]]:
    """Returns a client answering every request with the given status, and the requests it saw."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status_code, json=body if body is not None else {})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), seen


@pytest.fixture
def forbid_requests(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    """Replaces the client the tools build, so any request a tool makes is recorded, not sent.

    Returned so a test can assert the list is empty. A test that only asserted the raised error
    would pass even if the tool had already written to the real database first.
    """
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={})

    original = httpx.AsyncClient

    def build(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(handler)
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", build)
    return seen


async def test_returns_every_application_when_no_status_given() -> None:
    """An omitted status is not a filter: the whole log comes back."""
    client, _ = recording_client(200, APPLICATIONS)
    async with client:
        assert await fetch_applications(None, client) == APPLICATIONS


async def test_narrows_to_the_requested_status() -> None:
    """A status keeps only the applications holding it, in the order the API sent them."""
    client, _ = recording_client(200, APPLICATIONS)
    async with client:
        applications = await fetch_applications("applied", client)
    assert [application["company"] for application in applications] == ["Wix", "Gong"]


async def test_a_failed_read_carries_the_api_s_own_message() -> None:
    """Guards the read path against the generic SDK error the other two tools avoid."""
    client, _ = recording_client(500, {"detail": "database unreachable"})
    async with client:
        with pytest.raises(ToolError, match="database unreachable"):
            await fetch_applications(None, client)


async def test_a_refused_connection_names_the_api_and_the_address() -> None:
    """Guards the failure the first live call hit: a bare "error executing tool" with no cause."""

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(refuse)) as client:
        with pytest.raises(ToolError, match="not reachable") as raised:
            await fetch_applications(None, client)
    assert API_BASE_URL in str(raised.value)


async def test_a_stalled_backend_is_reported_like_an_unreachable_one() -> None:
    """A timeout is not a ConnectError, and means the same thing to whoever called the tool."""

    def stall(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(stall)) as client:
        with pytest.raises(ToolError, match="not reachable"):
            await fetch_applications(None, client)


async def test_unknown_status_is_rejected_before_any_request(
    forbid_requests: list[httpx.Request],
) -> None:
    """A status outside the pipeline is caught here rather than spent on a round trip."""
    with pytest.raises(ToolError, match="unknown status"):
        await list_applications(status="hired")
    assert forbid_requests == []


async def test_a_created_application_is_returned_as_stored() -> None:
    """Guards the expected-status check: a 201 is success, and the stored id is handed back."""
    client, seen = recording_client(201, {"id": "9", **JOB, "status": "saved"})
    async with client:
        created = await post_application({**JOB, "status": "saved", "notes": ""}, client)
    assert created["id"] == "9"
    assert seen[0].method == "POST"


async def test_a_new_application_defaults_to_saved_not_applied(
    forbid_requests: list[httpx.Request],
) -> None:
    """Guards the safety default: a misfired write notes a job, it does not claim one was sent."""
    with pytest.raises(ToolError):
        await log_application(**JOB)
    assert json.loads(forbid_requests[0].content)["status"] == "saved"


async def test_a_duplicate_url_says_the_job_is_already_tracked() -> None:
    """The API's 409 becomes advice to stop, which a bare status code does not give."""
    client, _ = recording_client(409, {"detail": "already tracked"})
    async with client:
        with pytest.raises(ToolError, match="already tracked"):
            await post_application({**JOB, "status": "saved", "notes": ""}, client)


async def test_unknown_status_is_rejected_before_writing_anything(
    forbid_requests: list[httpx.Request],
) -> None:
    """Nothing reaches the database when the status the caller named does not exist."""
    with pytest.raises(ToolError, match="unknown status"):
        await log_application(**JOB, status="hired")
    assert forbid_requests == []


async def test_a_status_change_sends_only_the_status() -> None:
    """Guards the PATCH contract: notes, dates and the link must survive a status change."""
    client, seen = recording_client(200, {"id": "9", **JOB, "status": "ghosted"})
    async with client:
        await patch_status("9", "ghosted", client)
    assert json.loads(seen[0].content) == {"status": "ghosted"}
    assert seen[0].method == "PATCH"


async def test_a_well_formed_id_that_no_longer_exists_says_to_list_first() -> None:
    """An id of the right shape that no row holds reaches the handler and returns 404."""
    client, _ = recording_client(404, {"detail": "Application not found"})
    async with client:
        with pytest.raises(ToolError, match="no application has id"):
            await patch_status(MISSING_ID, "ghosted", client)


async def test_an_invented_id_gets_the_same_answer_as_a_missing_one() -> None:
    """The API rejects a non-ObjectId with 422, which is the likelier way a model names a row."""
    client, _ = recording_client(422, {"detail": [{"type": "string_too_short"}]})
    async with client:
        with pytest.raises(ToolError, match="no application has id"):
            await patch_status("app-123", "ghosted", client)


async def test_an_unknown_status_is_rejected_before_overwriting_anything(
    forbid_requests: list[httpx.Request],
) -> None:
    """The status is checked before the PATCH, so a bad one cannot overwrite a good one."""
    with pytest.raises(ToolError, match="unknown status"):
        await update_status(MISSING_ID, "hired")
    assert forbid_requests == []
