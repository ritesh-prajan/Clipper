"""Main pipeline orchestrator for Live Stream Clipper."""

import argparse
import logging
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from clipper.approval import ApprovalQueue
from clipper.config import AppConfig
from clipper.db import Database
from clipper.openshorts_client import OpenShortsClient
from clipper.processor import ClipProcessor
from clipper.publisher import ClipRecord
from clipper.publisher.upload_post import UploadPostPublisher
from clipper.recorder import LiveStreamChunker

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("clipper.pipeline")


class Pipeline:
    """Coordinates stream chunking, OpenShorts AI processing, approval staging, and social publishing."""

    def __init__(self, config: AppConfig):
        """Initialize pipeline with validated AppConfig."""
        self.config = config
        self.config.output_dir.mkdir(parents=True, exist_ok=True)

        self.db = Database(self.config.output_dir / "pipeline_state.db")
        self.client = OpenShortsClient(
            base_url=self.config.openshorts_url,
            api_key=self.config.openshorts_api_key,
            upload_post_api_key=self.config.upload_post_api_key,
        )
        self.processor = ClipProcessor(
            config=self.config,
            db=self.db,
            client=self.client,
        )
        self.approval = ApprovalQueue(
            config=self.config,
            db=self.db,
        )
        self.publisher = UploadPostPublisher(
            config=self.config,
            db=self.db,
            client=self.client,
        )

        self.recorder: Optional[LiveStreamChunker] = None
        self.stop_event = threading.Event()
        self._publisher_thread: Optional[threading.Thread] = None

    def print_status(self) -> None:
        """Display current queue, processing, approval, and publication status."""
        state = self.db.resume_state()
        all_chunks = self.db.get_all_chunks()
        pending_chunks = len([c for c in all_chunks if c.get("status") in ("pending", "recorded")])
        completed_chunks = len([c for c in all_chunks if c.get("status") == "completed"])
        failed_chunks = len([c for c in all_chunks if c.get("status") == "failed"])

        pending_clips = len(state.get("pending_review") or [])
        approved_clips = len(state.get("approved_clips") or [])

        print("\n=======================================================")
        print("          Live Stream Clipper - Pipeline Status        ")
        print("=======================================================")
        print(f"Output Directory:    {self.config.output_dir.resolve()}")
        print(f"Recorded Chunks:     {len(all_chunks)} total ({completed_chunks} processed, {pending_chunks} pending, {failed_chunks} failed)")
        print(f"Queue Backlog:       {self.processor.work_queue.qsize()} chunk(s) in memory queue")
        print(f"Review Dashboard:    {pending_clips} clip(s) awaiting approval")
        print(f"Approved Clips:      {approved_clips} clip(s)")
        print(f"Auto Approve Mode:   {self.config.auto_approve}")
        print(f"Dry Run Mode:        {self.config.dry_run}")
        print("=======================================================\n")

    def _verify_server_connection(self) -> bool:
        """Verify connectivity to OpenShorts server with configurable retry backoff."""
        if self.client.test_connection():
            return True

        attempts = 0
        max_attempts = self.config.server_retry_max_attempts
        backoff = self.config.server_retry_backoff

        while attempts < max_attempts:
            if self.stop_event.is_set():
                return False
            attempts += 1
            logger.warning(
                "OpenShorts server unreachable at %s. Retrying attempt %d/%d in %.1fs...",
                self.config.openshorts_url,
                attempts,
                max_attempts,
                backoff,
            )
            time.sleep(backoff)
            backoff *= 2.0
            if self.client.test_connection():
                logger.info("Connected to OpenShorts server successfully!")
                return True

        return False

    def run(self) -> None:
        """Execute the primary pipeline lifecycle."""
        # 1. Print copyright notice if permission is not affirmed
        self.config.check_copyright_permission(raise_on_error=False)

        # 2. Check OpenShorts server connectivity (hard failure by default, or retry backoff)
        if not self.config.dry_run:
            connected = self._verify_server_connection()
            if not connected:
                raise RuntimeError(
                    f"OpenShorts server unreachable at {self.config.openshorts_url}. "
                    "Ensure OpenShorts backend is running or set dry_run=true."
                )

        # 3. Resume uncompleted chunks from DB
        resume_info = self.db.resume_state()
        for chunk in resume_info["pending_chunks"]:
            p = Path(chunk["path"])
            if p.exists():
                logger.info("Resuming unfinished chunk from database: %s", p.name)
                self.processor.enqueue_chunk(p)

        # 4. Start processor worker pool
        self.processor.start_workers()

        # 5. Start approval web server (if manual review is active)
        if not self.config.auto_approve:
            self.approval.start_server()
            self.approval.generate_html()

        # 6. Start background publisher loop
        self._publisher_thread = threading.Thread(
            target=self._publisher_loop,
            name="PublisherLoop",
            daemon=True,
        )
        self._publisher_thread.start()

        # 7. Check stream URL
        stream_url = self.config.stream_urls[0] if self.config.stream_urls else None
        if not stream_url:
            logger.error("No stream URL specified. Please provide via config.yaml or --stream-url.")
            self.stop()
            return

        # 8. Start recorder
        logger.info("Starting recorder for stream: %s", stream_url)
        self.recorder = LiveStreamChunker(
            stream_url=stream_url,
            output_dir=self.config.output_dir,
            chunk_seconds=self.config.chunk_seconds,
            overlap_seconds=self.config.overlap_seconds,
            quality=self.config.quality,
            max_offline_seconds=self.config.max_offline_seconds,
            ffprobe_check=self.config.ffprobe_check,
        )

        try:
            # Yield completed chunks as they are closed and verified
            for chunk_path in self.recorder.iter_completed_chunks():
                if self.stop_event.is_set():
                    break
                logger.info("New finalized chunk detected: %s", chunk_path.name)
                self.processor.enqueue_chunk(chunk_path)
        except KeyboardInterrupt:
            logger.info("Received KeyboardInterrupt. Initiating graceful shutdown...")
        finally:
            self.stop()

    def _publisher_loop(self) -> None:
        """Background loop continuously publishing approved clips to configured platforms."""
        logger.debug("Publisher loop started.")
        while not self.stop_event.is_set():
            if not self.config.i_own_or_have_permission:
                logger.warning(
                    "Auto-publishing refused: 'i_own_or_have_permission' is false. "
                    "Clips remain safely stored in review folder."
                )
                time.sleep(5.0)
                continue

            for platform in self.config.platforms:
                unposted_clips = self.db.get_approved_unposted_clips(platform)
                for clip_data in unposted_clips:
                    if self.stop_event.is_set():
                        break

                    clip_record = ClipRecord(
                        id=clip_data["id"],
                        job_id=clip_data["job_id"],
                        title=clip_data["title"],
                        path=Path(clip_data["path"]),
                        approved=clip_data["approved"],
                        posted_platforms=clip_data.get("posted_platforms", []),
                        created_at=clip_data["created_at"],
                    )

                    try:
                        self.publisher.post(clip_record)
                    except Exception as e:
                        logger.error("Error publishing clip %s to %s: %s", clip_record.title, platform, e)

            time.sleep(5.0)
        logger.debug("Publisher loop stopped.")

    def stop(self) -> None:
        """Perform graceful shutdown: stop recorder, drain queue, finish jobs, close client."""
        logger.info("Shutting down Live Stream Clipper pipeline...")
        self.stop_event.set()

        # Stop recorder
        if self.recorder:
            self.recorder.stop()

        # Stop processor workers
        self.processor.stop()

        # Stop approval server
        self.approval.stop_server()

        # Close client session
        self.client.close()
        logger.info("Pipeline shutdown complete.")


def parse_args(argv: Optional[list] = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Production Live Stream AI Clipper with OpenShorts."
    )
    parser.add_argument(
        "--config",
        "-c",
        default="config.yaml",
        help="Path to YAML configuration file (default: config.yaml).",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print database and queue status summary and exit.",
    )
    parser.add_argument(
        "--stream-url",
        "-u",
        help="Override or specify a live stream URL.",
    )
    parser.add_argument(
        "--auto-approve",
        action="store_true",
        help="Automatically approve and publish all generated clips without manual web review.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate ingestion and processing without calling OpenShorts or social networks.",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        help="Override output directory.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list] = None) -> None:
    """CLI entry point for the pipeline."""
    args = parse_args(argv)

    # Build overrides dictionary
    overrides = {}
    if args.stream_url:
        overrides["stream_urls"] = [args.stream_url]
    if args.auto_approve:
        overrides["auto_approve"] = True
    if args.dry_run:
        overrides["dry_run"] = True
    if args.output_dir:
        overrides["output_dir"] = Path(args.output_dir)

    # Load configuration
    config_file = args.config if Path(args.config).exists() else None
    if not config_file and Path("config.example.yaml").exists() and not Path("config.yaml").exists():
        logger.info("Using config.example.yaml as template.")
        config_file = "config.example.yaml"

    config = AppConfig.load(config_path=config_file, **overrides)

    pipeline = Pipeline(config)

    # Register POSIX / Windows signal handlers
    def sig_handler(signum, frame):
        logger.info("Signal %s received. Stopping...", signum)
        pipeline.stop()
        sys.exit(0)

    try:
        signal.signal(signal.SIGINT, sig_handler)
        signal.signal(signal.SIGTERM, sig_handler)
    except (ValueError, AttributeError):
        pass

    if args.status:
        pipeline.print_status()
        return

    pipeline.run()


if __name__ == "__main__":
    main()
