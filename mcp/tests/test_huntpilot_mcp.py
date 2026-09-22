"""Tests for the huntpilot MCP server.

The API is replaced with an ``httpx.MockTransport`` so the suite needs neither a running
backend nor a database.
"""

import json

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

import huntpilot_mcp
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


def make_client() -> httpx.AsyncClient:
    """Returns a client whose every request answers with the fixture list."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=APPLICATIONS)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_returns_every_application_when_no_status_given() -> None:
    async with make_client() as client:
        assert await fetch_applications(None, client) == APPLICATIONS


async def test_narrows_to_the_requested_status() -> None:
    async with make_client() as client:
        applications = await fetch_applications("applied", client)
    assert [application["company"] for application in applications] == ["Wix", "Gong"]


async def test_unknown_status_is_rejected_before_any_request() -> None:
    with pytest.raises(ToolError, match="unknown status"):
        await list_applications(status="hired")


async def test_a_refused_connection_names_the_api_and_the_address() -> None:
    """Guards the failure the first live call hit: a bare "error executing tool" with no cause."""

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(refuse)) as client:
        with pytest.raises(ToolError, match="not reachable") as raised:
            await fetch_applications(None, client)
    assert API_BASE_URL in str(raised.value)


JOB = {
    "company": "Kaltura",
    "role": "Implementation Specialist",
    "location": "Tel Aviv",
    "source": "LinkedIn",
    "url": "https://example.com/jobs/1",
}


def make_recording_client(status_code: int) -> tuple[httpx.AsyncClient, list[dict[str, object]]]:
    """Returns a client answering with the given status, and the list its requests land in."""
    sent: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(status_code, json={"id": "9", **JOB, "status": "saved"})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), sent


async def test_a_new_application_defaults_to_saved_not_applied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Guards the safety default: a misfired write notes a job, it does not claim one was sent.

    The tool is called the way a model calls it, with no status, and the posting step is replaced
    so the assertion is about the payload the tool built rather than about a stubbed response.
    """
    sent: dict[str, object] = {}

    async def capture(payload: dict[str, object], client: httpx.AsyncClient) -> dict[str, object]:
        sent.update(payload)
        return {"id": "9", **payload}

    monkeypatch.setattr(huntpilot_mcp, "post_application", capture)
    await log_application(**JOB)
    assert sent["status"] == "saved"


async def test_a_duplicate_url_says_the_job_is_already_tracked() -> None:
    client, _ = make_recording_client(409)
    async with client:
        with pytest.raises(ToolError, match="already tracked"):
            await post_application({**JOB, "status": "saved", "notes": ""}, client)


async def test_unknown_status_is_rejected_before_writing_anything() -> None:
    with pytest.raises(ToolError, match="unknown status"):
        await log_application(**JOB, status="hired")


async def test_a_status_change_sends_only_the_status() -> None:
    """Guards the PATCH contract: notes, dates and the link must survive a status change."""
    sent: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "9", **JOB, "status": "ghosted"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await patch_status("9", "ghosted", client)
    assert sent[0] == {"status": "ghosted"}


async def test_an_unknown_id_says_to_list_applications_first() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "Application not found"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ToolError, match="no application has id"):
            await patch_status("nope", "ghosted", client)


async def test_an_unknown_status_is_rejected_before_overwriting_anything() -> None:
    with pytest.raises(ToolError, match="unknown status"):
        await update_status("9", "hired")
