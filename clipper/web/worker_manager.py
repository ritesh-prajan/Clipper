"""Worker manager: manages per-source Pipeline threads.

Each source gets an isolated Pipeline instance running in its own thread.
The manager exposes start/stop/status methods and maintains a live stats dict
consumed by the dashboard and SSE streams.
"""

import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("clipper.web.worker_manager")

_DEFAULT_OUTPUT_BASE = Path("./live_output")


class SourceWorker:
    """Wraps a single Pipeline thread for one source."""

    def __init__(
        self,
        source_id: str,
        url: str,
        output_dir: Path,
        chunk_seconds: int,
        overlap_seconds: int,
        max_clips: int,
        openshorts_url: str,
        i_own_or_have_permission: bool,
        auto_approve: bool,
        dry_run: bool,
        on_status_change: Optional[Callable[[str, str], None]] = None,
        on_clip_created: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        self.source_id = source_id
        self.url = url
        self.output_dir = output_dir
        self.chunk_seconds = chunk_seconds
        self.overlap_seconds = overlap_seconds
        self.max_clips = max_clips
        self.openshorts_url = openshorts_url
        self.i_own_or_have_permission = i_own_or_have_permission
        self.auto_approve = auto_approve
        self.dry_run = dry_run
        self.on_status_change = on_status_change
        self.on_clip_created = on_clip_created

        self._thread: Optional[threading.Thread] = None
        self._pipeline = None
        self._status = "idle"
        self._chunks_done = 0
        self._clips_made = 0
        self._error: Optional[str] = None
        self._lock = threading.Lock()

    @property
    def status(self) -> str:
        return self._status

    @property
    def stats(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "status": self._status,
            "chunks_done": self._chunks_done,
            "clips_made": self._clips_made,
            "error": self._error,
        }

    def _set_status(self, status: str) -> None:
        self._status = status
        if self.on_status_change:
            try:
                self.on_status_change(self.source_id, status)
            except Exception:
                pass

    def start(self) -> bool:
        with self._lock:
            if self._thread and self._thread.is_alive():
                logger.warning("Source %s already running", self.source_id)
                return False
            self._set_status("starting")
            self._thread = threading.Thread(
                target=self._run,
                name=f"SourceWorker-{self.source_id[:8]}",
                daemon=True,
            )
            self._thread.start()
        return True

    def stop(self, timeout: float = 15.0) -> None:
        with self._lock:
            if self._pipeline:
                try:
                    self._pipeline.stop()
                except Exception as e:
                    logger.warning("Error stopping pipeline for %s: %s", self.source_id, e)
            self._set_status("stopped")
        if self._thread:
            self._thread.join(timeout=timeout)

    def _run(self) -> None:
        from clipper.config import AppConfig
        from clipper.pipeline import Pipeline

        logger.info("Starting pipeline for source %s: %s", self.source_id[:8], self.url)
        self._set_status("recording")

        try:
            config = AppConfig.load(
                stream_urls=[self.url],
                output_dir=self.output_dir,
                chunk_seconds=self.chunk_seconds,
                overlap_seconds=self.overlap_seconds,
                openshorts_url=self.openshorts_url,
                i_own_or_have_permission=self.i_own_or_have_permission,
                auto_approve=self.auto_approve,
                dry_run=self.dry_run,
                server_retry_max_attempts=5,
                server_retry_backoff=2.0,
            )
            self._pipeline = Pipeline(config)
            self._pipeline.run()
        except RuntimeError as e:
            self._error = str(e)
            logger.error("Pipeline error for source %s: %s", self.source_id[:8], e)
            self._set_status("error")
        except Exception as e:
            self._error = str(e)
            logger.error("Unexpected pipeline error for %s: %s", self.source_id[:8], e, exc_info=True)
            self._set_status("error")
        else:
            self._set_status("stopped")

        logger.info("Pipeline thread for source %s exited (status=%s)", self.source_id[:8], self._status)


class WorkerManager:
    """Manages all source workers and coordinates SSE event broadcasting."""

    def __init__(self, output_base: Path = _DEFAULT_OUTPUT_BASE):
        self.output_base = Path(output_base)
        self._workers: Dict[str, SourceWorker] = {}
        self._lock = threading.Lock()
        self._sse_queues: list = []  # list of asyncio.Queue for SSE
        self._sse_lock = threading.Lock()

    def _broadcast(self, event: str, data: Any) -> None:
        """Thread-safe broadcast to all SSE queues."""
        import asyncio
        with self._sse_lock:
            dead = []
            for q in self._sse_queues:
                try:
                    q.put_nowait({"event": event, "data": data})
                except Exception:
                    dead.append(q)
            for q in dead:
                self._sse_queues.remove(q)

    def register_sse_queue(self, q) -> None:
        with self._sse_lock:
            self._sse_queues.append(q)

    def unregister_sse_queue(self, q) -> None:
        with self._sse_lock:
            try:
                self._sse_queues.remove(q)
            except ValueError:
                pass

    def start_source(
        self,
        source_id: str,
        url: str,
        chunk_seconds: int,
        overlap_seconds: int,
        max_clips: int,
        openshorts_url: str,
        i_own_or_have_permission: bool,
        auto_approve: bool,
        dry_run: bool,
        output_dir: Optional[Path] = None,
    ) -> bool:
        effective_output = output_dir or (self.output_base / source_id)

        def on_status(sid: str, status: str):
            self._broadcast("pipeline_update", {"source_id": sid, "status": status})

        def on_clip(clip_data: Dict[str, Any]):
            self._broadcast("clip_created", clip_data)

        with self._lock:
            if source_id in self._workers and self._workers[source_id]._thread and \
               self._workers[source_id]._thread.is_alive():
                return False

            worker = SourceWorker(
                source_id=source_id,
                url=url,
                output_dir=effective_output,
                chunk_seconds=chunk_seconds,
                overlap_seconds=overlap_seconds,
                max_clips=max_clips,
                openshorts_url=openshorts_url,
                i_own_or_have_permission=i_own_or_have_permission,
                auto_approve=auto_approve,
                dry_run=dry_run,
                on_status_change=on_status,
                on_clip_created=on_clip,
            )
            self._workers[source_id] = worker

        return worker.start()

    def stop_source(self, source_id: str) -> bool:
        with self._lock:
            worker = self._workers.get(source_id)
        if not worker:
            return False
        worker.stop()
        return True

    def get_worker_status(self, source_id: str) -> Optional[str]:
        with self._lock:
            worker = self._workers.get(source_id)
        return worker.status if worker else None

    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return {sid: w.stats for sid, w in self._workers.items()}

    def stop_all(self) -> None:
        with self._lock:
            workers = list(self._workers.values())
        for w in workers:
            w.stop(timeout=5.0)
