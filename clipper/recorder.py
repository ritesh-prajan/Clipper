"""Live stream recording and chunking supervisor using FFmpeg and stream resolvers."""

import json
import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Generator, List, Optional, Set

logger = logging.getLogger("clipper.recorder")


def _refresh_windows_path() -> None:
    """Refresh PATH environment variable on Windows from User registry."""
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
                user_path, _ = winreg.QueryValueEx(key, "Path")
                for p in user_path.split(";"):
                    p = p.strip()
                    if p and p not in os.environ.get("PATH", ""):
                        os.environ["PATH"] = p + os.pathsep + os.environ.get("PATH", "")
        except Exception:
            pass


def check_preflight() -> None:
    """Validate that required external binaries (ffmpeg, and streamlink or yt-dlp) are available.

    Raises:
        RuntimeError: If ffmpeg or stream resolvers are missing.
    """
    _refresh_windows_path()
    if not shutil.which("ffmpeg"):
        raise RuntimeError(
            "FFmpeg binary not found on PATH. Please install FFmpeg:\n"
            "  Windows: winget install Gyan.FFmpeg\n"
            "  macOS:   brew install ffmpeg\n"
            "  Linux:   sudo apt install ffmpeg"
        )

    has_streamlink = shutil.which("streamlink") is not None
    has_ytdlp = shutil.which("yt-dlp") is not None

    if not (has_streamlink or has_ytdlp):
        raise RuntimeError(
            "Neither 'streamlink' nor 'yt-dlp' was found on PATH. Please install at least one:\n"
            "  pip install streamlink yt-dlp"
        )


class LiveStreamChunker:
    """Manages stream recording into rolling MP4 chunks with FFmpeg process supervision."""

    def __init__(
        self,
        stream_url: str,
        output_dir: Path,
        chunk_seconds: int = 600,
        overlap_seconds: int = 20,
        quality: str = "best",
        max_offline_seconds: int = 3600,
        ffprobe_check: bool = True,
    ):
        """Initialize the chunker.

        Args:
            stream_url: Live stream URL (Twitch, YouTube, Kick, or direct stream/file).
            output_dir: Root output directory. Chunks are stored in output_dir / 'chunks'.
            chunk_seconds: Desired chunk duration in seconds.
            overlap_seconds: Overlap between segments in seconds.
            quality: Desired stream quality (e.g. 'best').
            max_offline_seconds: Maximum total offline time before abandoning recording.
            ffprobe_check: Whether to perform ffprobe validation on closed chunks.
        """
        self.stream_url = stream_url
        self.output_dir = Path(output_dir)
        self.chunks_dir = self.output_dir / "chunks"
        self.chunks_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.chunks_dir / "ffmpeg_recorder.log"

        self.chunk_seconds = chunk_seconds
        self.overlap_seconds = overlap_seconds
        self.quality = quality
        self.max_offline_seconds = max_offline_seconds
        self.ffprobe_check = ffprobe_check

        if self.overlap_seconds > 0:
            self.step_seconds = max(1, self.chunk_seconds - self.overlap_seconds)
            self.raw_dir = self.chunks_dir / "raw"
            self.raw_dir.mkdir(parents=True, exist_ok=True)
            self.segment_list_file = self.raw_dir / "raw_segments.txt"
        else:
            self.step_seconds = self.chunk_seconds
            self.raw_dir = None
            self.segment_list_file = self.chunks_dir / "segments.txt"

        self._raw_segment_counter = 0
        self._completed_raw_segments: List[Path] = []
        self._built_chunk_indices: Set[int] = set()

        self.stop_event = threading.Event()
        self.ffmpeg_proc: Optional[subprocess.Popen] = None
        self._stderr_file: Optional[open] = None

        # Preflight verification on initialization
        check_preflight()

    def resolve_stream_url(self) -> Optional[str]:
        """Resolve webpage stream URL to a direct HLS/m3u8 or media stream URL.

        Attempts streamlink first, then yt-dlp, and falls back to direct URL or local file.
        """
        _refresh_windows_path()

        # Check if URL is already a local file path
        try:
            if Path(self.stream_url).exists():
                return self.stream_url
        except Exception:
            pass

        # 1. Try streamlink
        if shutil.which("streamlink"):
            logger.info("Resolving stream URL via streamlink: %s", self.stream_url)
            try:
                cmd = ["streamlink", "--stream-url", self.stream_url, self.quality]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
                if res.returncode == 0 and res.stdout.strip().startswith("http"):
                    direct_url = res.stdout.strip()
                    logger.info("Stream URL resolved successfully via streamlink.")
                    return direct_url
            except Exception as e:
                logger.warning("streamlink resolution failed: %s", e)

        # 2. Try yt-dlp
        if shutil.which("yt-dlp"):
            logger.info("Resolving stream URL via yt-dlp: %s", self.stream_url)
            try:
                cmd = ["yt-dlp", "--remote-components", "ejs:github", "--no-warnings", "-g", "-f", "best", self.stream_url]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                if res.returncode == 0 and res.stdout.strip().startswith("http"):
                    direct_url = res.stdout.strip().split("\n")[0].strip()
                    logger.info("Stream URL resolved successfully via yt-dlp.")
                    return direct_url
            except Exception as e:
                logger.warning("yt-dlp resolution failed: %s", e)

        # 3. Direct URL fallback (m3u8, RTMP, HTTP)
        if self.stream_url.startswith(("http://", "https://", "rtmp://")):
            return self.stream_url

        logger.error("Could not resolve stream URL: %s", self.stream_url)
        return None

    def start_recording(self) -> bool:
        """Launch the FFmpeg segmenter process.

        Redirects stderr to a log file on disk and stdout to DEVNULL (never pipes),
        preventing deadlocks.
        """
        direct_url = self.resolve_stream_url()
        if not direct_url:
            return False

        # Ensure previous process is closed
        self._close_ffmpeg()

        # Open rotating / append log file for stderr
        self._stderr_file = open(self.log_file, "a", encoding="utf-8", errors="replace")

        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "warning",
        ]

        # Reconnect flags are only supported on network HTTP/HTTPS protocols
        if direct_url.startswith(("http://", "https://")):
            cmd.extend([
                "-reconnect", "1",
                "-reconnect_at_eof", "1",
                "-reconnect_streamed", "1",
                "-reconnect_delay_max", "10",
            ])

        cmd.extend([
            "-i", direct_url,
            "-c", "copy",
            "-f", "segment",
            "-segment_time", str(self.step_seconds),
            "-segment_format", "mp4",
            "-reset_timestamps", "1",
            "-segment_list", str(self.segment_list_file),
            "-segment_list_type", "flat",
            "-segment_list_flags", "+live",
            "-segment_start_number", str(self._raw_segment_counter),
        ])

        if self.overlap_seconds > 0:
            segment_pattern = str(self.raw_dir / "raw_%04d.mp4")
        else:
            segment_pattern = str(self.chunks_dir / "chunk_%04d.mp4")

        cmd.append(segment_pattern)

        logger.info(
            "Starting FFmpeg recorder: step=%ss, chunk_len=%ss, overlap=%ss",
            self.step_seconds,
            self.chunk_seconds,
            self.overlap_seconds,
        )
        try:
            self.ffmpeg_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=self._stderr_file,
            )
            return True
        except Exception as e:
            logger.error("Failed to spawn FFmpeg process: %s", e)
            return False

    def validate_chunk_ffprobe(self, chunk_path: Path) -> bool:
        """Validate that the chunk exists, is readable, and represents a complete video container."""
        if not chunk_path.exists() or chunk_path.stat().st_size == 0:
            return False

        if not self.ffprobe_check:
            return chunk_path.stat().st_size > 100_000

        _refresh_windows_path()
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            str(chunk_path),
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if res.returncode != 0:
                return False
            data = json.loads(res.stdout)
            format_info = data.get("format", {})
            duration = float(format_info.get("duration", 0))
            return duration > 0.0
        except Exception as e:
            logger.warning("ffprobe validation failed for %s: %s", chunk_path.name, e)
            return False

    def _build_overlapping_chunk(self, chunk_index: int, seg_a: Path, seg_b: Optional[Path]) -> Optional[Path]:
        """Build an overlapping chunk from raw segments using stream copy concat cutting."""
        _refresh_windows_path()
        chunk_path = self.chunks_dir / f"chunk_{chunk_index:04d}.mp4"
        if chunk_path.exists() and self.validate_chunk_ffprobe(chunk_path):
            return chunk_path

        if seg_b is not None:
            concat_txt = self.raw_dir / f"concat_{chunk_index}.txt"
            fa = str(seg_a.resolve()).replace("\\", "/")
            fb = str(seg_b.resolve()).replace("\\", "/")
            concat_txt.write_text(f"file '{fa}'\nfile '{fb}'\n", encoding="utf-8")

            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel", "warning",
                "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_txt),
                "-c", "copy",
                "-ss", "0",
                "-t", str(self.chunk_seconds),
                str(chunk_path),
            ]
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                if concat_txt.exists():
                    try:
                        concat_txt.unlink()
                    except OSError:
                        pass
                if res.returncode == 0 and self.validate_chunk_ffprobe(chunk_path):
                    return chunk_path
                else:
                    logger.warning("FFmpeg concat failed for %s: %s", chunk_path.name, res.stderr)
            except Exception as e:
                logger.error("Error creating overlapping chunk %s: %s", chunk_path.name, e)
        else:
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel", "warning",
                "-y",
                "-i", str(seg_a),
                "-c", "copy",
                str(chunk_path),
            ]
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                if res.returncode == 0 and self.validate_chunk_ffprobe(chunk_path):
                    return chunk_path
                else:
                    logger.warning("FFmpeg copy failed for final chunk %s: %s", chunk_path.name, res.stderr)
            except Exception as e:
                logger.error("Error creating final chunk %s: %s", chunk_path.name, e)

        return None

    def iter_completed_chunks(self) -> Generator[Path, None, None]:
        """Generator yielding newly completed and validated chunk paths.

        Supervises FFmpeg with exponential backoff on stream disconnection.
        Flushes the final chunk upon shutdown before returning.
        """
        seen_chunks: Set[str] = set()
        backoff_seconds = 1.0
        max_backoff = 60.0
        offline_start: Optional[float] = None

        # Start initial recording
        if not self.start_recording():
            offline_start = time.time()

        try:
            while not self.stop_event.is_set():
                # 1. Supervise FFmpeg process
                proc_active = self.ffmpeg_proc is not None and self.ffmpeg_proc.poll() is None

                if not proc_active:
                    now = time.time()
                    if offline_start is None:
                        offline_start = now
                        logger.warning("FFmpeg recorder stopped. Entering reconnection supervisor loop.")

                    elapsed_offline = now - offline_start
                    if self.max_offline_seconds <= 0 or elapsed_offline >= self.max_offline_seconds:
                        logger.info(
                            "FFmpeg process inactive and max_offline_seconds reached (%s). Stopping recorder.",
                            self.max_offline_seconds,
                        )
                        break

                    logger.info("Attempting stream restart in %.1fs (offline elapsed: %.1fs)...", backoff_seconds, elapsed_offline)
                    time.sleep(backoff_seconds)
                    backoff_seconds = min(backoff_seconds * 2.0, max_backoff)

                    if self.start_recording():
                        logger.info("FFmpeg recorder successfully restarted!")
                        offline_start = None
                        backoff_seconds = 1.0
                else:
                    offline_start = None
                    backoff_seconds = 1.0

                # 2. Check segment list and yield ready chunks
                yield from self._scan_and_yield_chunks(seen_chunks, is_final=False)

                # Poll interval
                time.sleep(2.0)

        finally:
            # Shutdown and final flush
            self.stop()
            logger.info("Recorder stopped. Performing final flush scan...")
            yield from self._scan_and_yield_chunks(seen_chunks, is_final=True)

    def _scan_and_yield_chunks(self, seen_chunks: Set[str], is_final: bool = False) -> Generator[Path, None, None]:
        """Scan segment list and yield valid chunks that have not yet been yielded."""
        if not self.segment_list_file.exists():
            return

        try:
            with open(self.segment_list_file, "r", encoding="utf-8") as f:
                entries = [line.strip() for line in f if line.strip()]
        except Exception as e:
            logger.warning("Error reading %s: %s", self.segment_list_file.name, e)
            return

        if self.overlap_seconds == 0:
            for entry in entries:
                if entry in seen_chunks:
                    continue
                chunk_path = self.chunks_dir / entry
                if self.validate_chunk_ffprobe(chunk_path):
                    seen_chunks.add(entry)
                    logger.info("Yielding finalized chunk: %s", chunk_path.name)
                    yield chunk_path
            return

        # Overlapping mode: read raw segments and construct overlapping chunks
        for entry in entries:
            raw_path = self.raw_dir / entry
            if raw_path not in self._completed_raw_segments:
                if self.validate_chunk_ffprobe(raw_path):
                    self._completed_raw_segments.append(raw_path)
                    self._raw_segment_counter = max(self._raw_segment_counter, len(self._completed_raw_segments))

        # Build chunks where both seg_i and seg_{i+1} exist
        total_raw = len(self._completed_raw_segments)
        for i in range(total_raw - 1):
            if i in self._built_chunk_indices:
                continue
            seg_a = self._completed_raw_segments[i]
            seg_b = self._completed_raw_segments[i + 1]
            chunk_path = self._build_overlapping_chunk(i, seg_a, seg_b)
            if chunk_path is not None:
                self._built_chunk_indices.add(i)
                seen_chunks.add(chunk_path.name)
                logger.info("Yielding overlapping chunk: %s (covering segments %d & %d)", chunk_path.name, i, i + 1)
                yield chunk_path

        # If final flush, also build final tail chunk from the last raw segment
        if is_final and total_raw > 0:
            last_idx = total_raw - 1
            if last_idx not in self._built_chunk_indices:
                seg_last = self._completed_raw_segments[last_idx]
                chunk_path = self._build_overlapping_chunk(last_idx, seg_last, None)
                if chunk_path is not None:
                    self._built_chunk_indices.add(last_idx)
                    seen_chunks.add(chunk_path.name)
                    logger.info("Yielding final tail chunk: %s (segment %d)", chunk_path.name, last_idx)
                    yield chunk_path

    def stop(self) -> None:
        """Stop the recorder and terminate the FFmpeg process cleanly."""
        self.stop_event.set()
        self._close_ffmpeg()

    def _close_ffmpeg(self) -> None:
        """Terminate and clean up FFmpeg subprocess and stderr handle."""
        if self.ffmpeg_proc and self.ffmpeg_proc.poll() is None:
            logger.info("Terminating FFmpeg recording process (PID %s)...", self.ffmpeg_proc.pid)
            self.ffmpeg_proc.terminate()
            try:
                self.ffmpeg_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                logger.warning("FFmpeg process did not exit within 10s; sending SIGKILL.")
                self.ffmpeg_proc.kill()
        self.ffmpeg_proc = None

        if self._stderr_file and not self._stderr_file.closed:
            try:
                self._stderr_file.flush()
                self._stderr_file.close()
            except Exception:
                pass
        self._stderr_file = None
