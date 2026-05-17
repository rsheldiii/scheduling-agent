"""Compose FastAPI (Twilio adapter) and FastMCP (scheduling tools) into one ASGI app."""
import asyncio
import logging

from anyio import ClosedResourceError
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from .server import app, _get_bearer_token
from .mcp_server import mcp

logger = logging.getLogger(__name__)


class _BearerAuthMiddleware:
    """Reject /mcp requests that don't carry a valid Bearer token."""

    def __init__(self, asgi_app: ASGIApp) -> None:
        self.app = asgi_app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            request = Request(scope, receive)
            auth = request.headers.get("Authorization", "")
            if not auth.startswith("Bearer ") or auth[len("Bearer "):] != _get_bearer_token():
                response = Response("Unauthorized", status_code=401)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


# Build the MCP ASGI app — also initializes the session manager lazily.
_mcp_asgi = mcp.streamable_http_app()
app.mount("/mcp", _BearerAuthMiddleware(_mcp_asgi))

# The StreamableHTTPSessionManager requires its task group to be running before
# any request arrives. Starlette doesn't propagate lifespan to mounted sub-apps,
# so we start it explicitly here as a long-lived background task.
_mcp_session_task: asyncio.Task | None = None


@app.on_event("startup")
async def _start_mcp_session() -> None:
    global _mcp_session_task

    async def _run() -> None:
        async with mcp.session_manager.run():
            await asyncio.Future()  # runs until cancelled

    _mcp_session_task = asyncio.create_task(_run())


@app.on_event("shutdown")
async def _stop_mcp_session() -> None:
    if _mcp_session_task and not _mcp_session_task.done():
        _mcp_session_task.cancel()
        try:
            await _mcp_session_task
        except asyncio.CancelledError:
            pass


class _SuppressMcpDisconnect:
    """Swallow ClosedResourceError that bubbles up when an MCP client disconnects
    mid-tool. The connection is already dead at that point so the error is noise."""

    def __init__(self, asgi_app):
        self.app = asgi_app

    async def __call__(self, scope, receive, send):
        try:
            await self.app(scope, receive, send)
        except* ClosedResourceError:
            logger.info("MCP client disconnected during tool execution")


app = _SuppressMcpDisconnect(app)  # type: ignore[assignment]
