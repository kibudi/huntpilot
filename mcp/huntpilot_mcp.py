"""MCP server exposing the huntpilot application log to Claude Code.

The server owns no data. Every tool calls the FastAPI backend over HTTP, so the API stays the
sole owner of the database and its validation still applies to anything this server asks for.
The cost is that huntpilot must be running when a tool is called; the benefit is that the two
can never disagree about what an application is.

Every failure a caller could act on is raised as ``ToolError``. It is the only exception whose
message reaches the caller: the SDK replaces anything else with a generic "error executing
tool", which says that something broke but not what, and leaves a model with nothing to retry
or report. Unreachable backends, unknown identifiers and rejected values are all translated
here for that reason.

The module is named ``huntpilot_mcp`` rather than ``mcp`` so that it cannot shadow the SDK
package of that name when this directory ends up on ``sys.path``.
"""

from http import HTTPStatus
from typing import Any, Final

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

API_BASE_URL: Final = "http://localhost:8000"
STATUSES: Final = ("saved", "applied", "interview", "offer", "rejected", "ghosted")
REQUEST_TIMEOUT: Final = 10.0

server = MCPServer("huntpilot")


async def send(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    json: dict[str, Any] | None = None,
) -> httpx.Response:
    """Makes one request to the API, translating any transport failure into ``ToolError``.

    ``httpx.TransportError`` is caught rather than ``ConnectError`` alone: a backend that
    accepts the socket and then stalls, mid-startup or blocked on its database, raises a
    timeout instead, which is not a ``ConnectError`` and would otherwise escape as the generic
    message this module exists to avoid. Both mean the same thing to the caller.

    The response is returned unexamined. Which status codes are expected differs per endpoint,
    so each caller interprets its own.
    """
    try:
        return await client.request(method, f"{API_BASE_URL}{path}", json=json)
    except httpx.TransportError as error:
        raise ToolError(
            f"the huntpilot API is not reachable at {API_BASE_URL} - is it running?"
        ) from error


def reject(action: str, response: httpx.Response) -> ToolError:
    """Builds the error for a status code no caller expected, keeping the API's own message.

    The body is included because it carries the API's validation detail, which names the field
    at fault; the status code alone would send a caller looking in the wrong place.
    """
    return ToolError(f"huntpilot rejected the {action} ({response.status_code}): {response.text}")


async def fetch_applications(
    status: str | None,
    client: httpx.AsyncClient,
) -> list[dict[str, Any]]:
    """Returns tracked applications from the API, optionally narrowed to one pipeline status.

    The filtering happens here rather than in the request because ``GET /api/applications``
    takes no status parameter. Pushing it into the API is the better fix, but it is a change to
    a shipped endpoint and belongs in its own step.

    The client is passed in rather than created here so tests can supply a mock transport
    instead of requiring a running backend.
    """
    response = await send(client, "GET", "/api/applications")
    if response.status_code != HTTPStatus.OK:
        raise reject("request", response)
    applications: list[dict[str, Any]] = response.json()
    if status is None:
        return applications
    return [application for application in applications if application["status"] == status]


@server.tool(annotations=ToolAnnotations(read_only_hint=True))
async def list_applications(status: str | None = None) -> list[dict[str, Any]]:
    """List tracked job applications, most recently updated first.

    Pass a status to see only part of the pipeline: saved, applied, interview, offer, rejected
    or ghosted. Omit it to see everything.

    The docstring is the tool description the model reads when deciding whether to call this,
    so it names the valid statuses instead of leaving them to be guessed.
    """
    if status is not None and status not in STATUSES:
        raise ToolError(f"unknown status {status!r}; expected one of {', '.join(STATUSES)}")
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        return await fetch_applications(status, client)


async def post_application(
    payload: dict[str, Any],
    client: httpx.AsyncClient,
) -> dict[str, Any]:
    """Creates one application through the API and returns it as stored.

    The 409 the API raises on a duplicate url is translated rather than passed through, because
    it is the expected outcome of asking twice about the same job: the caller should stop rather
    than retry, which a bare status code does not say.

    Like ``fetch_applications``, the client is a parameter so tests need no running backend.
    """
    response = await send(client, "POST", "/api/applications", json=payload)
    if response.status_code == HTTPStatus.CONFLICT:
        raise ToolError(f"this job is already tracked: {payload['url']}")
    if response.status_code != HTTPStatus.CREATED:
        raise reject("application", response)
    created: dict[str, Any] = response.json()
    return created


@server.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False))
async def log_application(
    company: str,
    role: str,
    location: str,
    source: str,
    url: str,
    status: str = "saved",
    notes: str = "",
) -> dict[str, Any]:
    """Track a new job application in huntpilot.

    Use this when a job posting should be saved, tracked or logged. All of company, role,
    location, source and url are required: source is where the job was found, such as LinkedIn,
    Comeet or a company careers page, and url is the posting link, which must be unique.

    Status defaults to saved, meaning noted but not yet applied to. Pass applied only when the
    application has actually been sent.

    Returns the application as stored, including the id huntpilot assigned it.
    """
    if status not in STATUSES:
        raise ToolError(f"unknown status {status!r}; expected one of {', '.join(STATUSES)}")
    payload = {
        "company": company,
        "role": role,
        "location": location,
        "source": source,
        "url": url,
        "status": status,
        "notes": notes,
    }
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        return await post_application(payload, client)


async def patch_status(
    application_id: str,
    status: str,
    client: httpx.AsyncClient,
) -> dict[str, Any]:
    """Moves one application to a new pipeline status and returns it as stored.

    Only ``status`` is sent. A PATCH writes just the fields present in the body, so every other
    field, including notes, dates and the posting link, is left untouched by construction rather
    than by resending values this tool never read.

    Both ways of naming the wrong application get the same answer. The API declares the path
    parameter as an ``ObjectId``, so an invented identifier fails its validation with a 422
    before the handler runs, while a well-formed one that no longer exists reaches the handler
    and returns 404. A caller that guessed an id cannot tell those apart and does not need to:
    either way the fix is to list the applications and use an id from that.
    """
    response = await send(
        client, "PATCH", f"/api/applications/{application_id}", json={"status": status}
    )
    if response.status_code in (HTTPStatus.NOT_FOUND, HTTPStatus.UNPROCESSABLE_ENTITY):
        raise ToolError(
            f"no application has id {application_id!r}; "
            "list the applications first and use an id from that"
        )
    if response.status_code != HTTPStatus.OK:
        raise reject("change", response)
    updated: dict[str, Any] = response.json()
    return updated


@server.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=True))
async def update_status(application_id: str, status: str) -> dict[str, Any]:
    """Move one tracked application to a different pipeline status.

    Use this to record that a job progressed or ended: saved, applied, interview, offer,
    rejected or ghosted. Ghosted means applied but never answered.

    The id is the one huntpilot assigned, as returned by list_applications. Nothing else about
    the application is changed. The previous status is overwritten and not recoverable, so
    confirm which application is meant before calling this on several at once.
    """
    if status not in STATUSES:
        raise ToolError(f"unknown status {status!r}; expected one of {', '.join(STATUSES)}")
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        return await patch_status(application_id, status, client)


def main() -> None:
    """Runs the server over stdio, the transport Claude Code launches it with."""
    server.run()


if __name__ == "__main__":
    main()
