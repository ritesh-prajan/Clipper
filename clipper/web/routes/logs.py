"""Logs SSE route: stream live pipeline log lines to browser."""

import asyncio
import json
import logging
import queue
import threading
from typing import AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

logger = logging.getLogger("clipper.web.routes.logs")
router = APIRouter(prefix="/api/logs", tags=["logs"])

# Global log queue for SSE consumers
_LOG_QUEUE: queue.Queue = queue.Queue(maxsize=10000)
_SECRETS: list[str] = []  # populated at startup


def register_secret(secret: str) -> None:
    """Register a secret to redact from live logs."""
    if secret and secret not in _SECRETS:
        _SECRETS.append(secret)


def _redact(message: str) -> str:
    for s in _SECRETS:
        if s and len(s) > 4:
            message = message.replace(s, "••••")
    return message


class _SSELogHandler(logging.Handler):
    """Logging handler that pushes log records to the SSE queue."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            msg = _redact(msg)
            _LOG_QUEUE.put_nowait({
                "level": record.levelname,
                "logger": record.name,
                "message": msg,
                "timestamp": record.created,
            })
        except Exception:
            pass  # Never let the log handler crash


def install_sse_log_handler() -> None:
    """Install the SSE log handler on the root logger once at startup."""
    root = logging.getLogger()
    for h in root.handlers:
        if isinstance(h, _SSELogHandler):
            return  # Already installed
    handler = _SSELogHandler()
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s", "%H:%M:%S")
    handler.setFormatter(formatter)
    root.addHandler(handler)


@router.get("/stream")
async def log_stream(request: Request):
    """SSE endpoint: pushes live log lines to the browser."""

    async def event_generator() -> AsyncGenerator[str, None]:
        loop = asyncio.get_event_loop()
        while True:
            if await request.is_disconnected():
                break
            try:
                # Non-blocking drain — convert sync queue to async
                items = []
                for _ in range(50):
                    try:
                        items.append(_LOG_QUEUE.get_nowait())
                    except queue.Empty:
                        break

                for item in items:
                    data = json.dumps(item)
                    yield f"event: log_line\ndata: {data}\n\n"

                if not items:
                    await asyncio.sleep(0.5)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(1.0)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/recent")
async def recent_logs(request: Request, limit: int = 200):
    """Return the last N log lines from the in-memory queue (non-streaming)."""
    items = []
    temp_q: list = []
    for _ in range(min(limit, _LOG_QUEUE.qsize())):
        try:
            temp_q.append(_LOG_QUEUE.get_nowait())
        except queue.Empty:
            break
    # Put them back
    for item in temp_q:
        try:
            _LOG_QUEUE.put_nowait(item)
        except queue.Full:
            pass
    return {"logs": temp_q[-limit:]}
