"""MCP server exposing the huntpilot application log to Claude Code.

The server owns no data. Every tool calls the FastAPI backend over HTTP, so the API stays the
sole owner of the database and its validation still applies to anything this server asks for.
The cost is that huntpilot must be running when a tool is called; the benefit is that the two
can never disagree about what an application is.

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

server = MCPServer("huntpilot")


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

    A refused connection is re-raised as ``ToolError`` naming the address, because that is the
    expected failure of this design — the backend owns the data and may simply be down — and
    the SDK replaces any other exception with a generic message the caller cannot act on.
    """
    try:
        response = await client.get(f"{API_BASE_URL}/api/applications")
    except httpx.ConnectError as error:
        raise ToolError(
            f"the huntpilot API is not reachable at {API_BASE_URL} - is it running?"
        ) from error
    response.raise_for_status()
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

    Failures are raised as ``ToolError`` for the same reason: the message is what the caller
    reads, so it has to say what went wrong rather than that something did.
    """
    if status is not None and status not in STATUSES:
        raise ToolError(f"unknown status {status!r}; expected one of {', '.join(STATUSES)}")
    async with httpx.AsyncClient(timeout=10.0) as client:
        return await fetch_applications(status, client)


async def post_application(
    payload: dict[str, Any],
    client: httpx.AsyncClient,
) -> dict[str, Any]:
    """Creates one application through the API and returns it as stored.

    The 409 the API raises on a duplicate url is translated rather than passed through, because
    it is the expected outcome of asking twice about the same job and the caller can act on it.
    Any other error status is reported with its body, which carries the API's own validation
    message.

    Like ``fetch_applications``, the client is a parameter so tests need no running backend.
    """
    try:
        response = await client.post(f"{API_BASE_URL}/api/applications", json=payload)
    except httpx.ConnectError as error:
        raise ToolError(
            f"the huntpilot API is not reachable at {API_BASE_URL} - is it running?"
        ) from error
    if response.status_code == HTTPStatus.CONFLICT:
        raise ToolError(f"this job is already tracked: {payload['url']}")
    if response.status_code != HTTPStatus.CREATED:
        raise ToolError(f"huntpilot rejected the application ({response.status_code}): {response.text}")
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
    async with httpx.AsyncClient(timeout=10.0) as client:
        return await post_application(payload, client)

async def patch_status(
    application_id: str,
    status: str,
    client: httpx.AsyncClient,
) -> dict[str, Any]:
    """Moves one application to a new pipeline status and returns it as stored.

    Only ``status`` is sent. A PATCH writes just the fields present in the body, so every other
    field — notes, dates, the posting link — is left untouched by construction rather than by
    resending values this tool never read.

    A 404 is translated because it is the likely mistake: an identifier copied from an older
    listing, or invented. The message says so rather than reporting the bare status code.
    """
    try:
        response = await client.patch(
            f"{API_BASE_URL}/api/applications/{application_id}", json={"status": status}
        )
    except httpx.ConnectError as error:
        raise ToolError(
            f"the huntpilot API is not reachable at {API_BASE_URL} - is it running?"
        ) from error
    if response.status_code == HTTPStatus.NOT_FOUND:
        raise ToolError(
            f"no application has id {application_id!r}; list them first and use an id from that"
        )
    if response.status_code != HTTPStatus.OK:
        raise ToolError(f"huntpilot rejected the change ({response.status_code}): {response.text}")
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
    async with httpx.AsyncClient(timeout=10.0) as client:
        return await patch_status(application_id, status, client)

def main() -> None:
    """Runs the server over stdio, the transport Claude Code launches it with."""
    server.run()


if __name__ == "__main__":
    main()
