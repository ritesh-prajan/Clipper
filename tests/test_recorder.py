"""Unit and integration tests for LiveStreamChunker recorder."""

import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from clipper.recorder import LiveStreamChunker, _refresh_windows_path, check_preflight


def test_preflight_missing_ffmpeg():
    """Verify check_preflight raises RuntimeError when ffmpeg is missing."""
    with patch("shutil.which", return_value=None):
        with pytest.raises(RuntimeError, match="FFmpeg binary not found"):
            check_preflight()


def test_preflight_missing_streamlink_and_ytdlp():
    """Verify check_preflight raises RuntimeError when both stream resolvers are missing."""
    def fake_which(cmd):
        if cmd == "ffmpeg":
            return "/usr/bin/ffmpeg"
        return None

    with patch("shutil.which", side_effect=fake_which):
        with pytest.raises(RuntimeError, match="Neither 'streamlink' nor 'yt-dlp' was found"):
            check_preflight()


def test_iter_completed_chunks_ffprobe_filtering(tmp_path: Path):
    """Verify iter_completed_chunks yields only ffprobe-valid chunks and skips duplicates in non-overlap mode."""
    with patch("clipper.recorder.check_preflight"):
        chunker = LiveStreamChunker(
            stream_url="https://twitch.tv/test",
            output_dir=tmp_path,
            chunk_seconds=10,
            overlap_seconds=0,
            ffprobe_check=True,
        )

        chunk1 = chunker.chunks_dir / "chunk_0001.mp4"
        chunk2 = chunker.chunks_dir / "chunk_0002.mp4"
        chunk1.write_bytes(b"valid_data")
        chunk2.write_bytes(b"invalid_data")

        # Write segments list
        chunker.segment_list_file.write_text("chunk_0001.mp4\nchunk_0002.mp4\n", encoding="utf-8")

        # Mock ffprobe validation: chunk1 is valid, chunk2 is invalid
        def mock_validate(path: Path) -> bool:
            return path.name == "chunk_0001.mp4"

        chunker.validate_chunk_ffprobe = mock_validate

        # Mock start_recording and ffmpeg process poll
        chunker.start_recording = MagicMock(return_value=True)
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0  # Process has exited
        chunker.ffmpeg_proc = mock_proc

        # Stop after one iteration
        def trigger_stop(*args, **kwargs):
            chunker.stop_event.set()

        with patch("time.sleep", side_effect=trigger_stop):
            yielded = list(chunker.iter_completed_chunks())

        # Verify only valid chunk was yielded and no duplicates
        assert len(yielded) == 1
        assert yielded[0].name == "chunk_0001.mp4"


def test_iter_completed_chunks_yields_final_chunk_on_exit(tmp_path: Path):
    """Verify that any chunk closed right as FFmpeg exits is yielded in final flush."""
    with patch("clipper.recorder.check_preflight"):
        chunker = LiveStreamChunker(
            stream_url="https://twitch.tv/test",
            output_dir=tmp_path,
            chunk_seconds=10,
            overlap_seconds=0,
            ffprobe_check=False,
        )

        final_chunk = chunker.chunks_dir / "chunk_final.mp4"
        final_chunk.write_bytes(b"final_chunk_bytes" * 1000)
        chunker.segment_list_file.write_text("chunk_final.mp4\n", encoding="utf-8")

        chunker.start_recording = MagicMock(return_value=True)
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0
        chunker.ffmpeg_proc = mock_proc

        chunker.validate_chunk_ffprobe = MagicMock(return_value=True)

        # Trigger stop immediately
        chunker.stop_event.set()
        yielded = list(chunker.iter_completed_chunks())

        assert len(yielded) == 1
        assert yielded[0].name == "chunk_final.mp4"


def test_real_ffmpeg_recording_with_overlap(tmp_path: Path):
    """Integration test running actual FFmpeg on a testsrc stream asserting overlap windows work without crashing."""
    _refresh_windows_path()
    ffmpeg_bin = shutil.which("ffmpeg")
    ffprobe_bin = shutil.which("ffprobe")
    if not (ffmpeg_bin and ffprobe_bin):
        pytest.skip("Real FFmpeg or FFprobe binary not installed on system PATH")

    # 1. Generate a small test MP4 video with lavfi testsrc (12 seconds)
    test_src = tmp_path / "testsrc_input.mp4"
    gen_cmd = [
        ffmpeg_bin,
        "-y",
        "-f", "lavfi",
        "-i", "testsrc=duration=12:size=320x240:rate=30",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-g", "30",
        str(test_src),
    ]
    gen_res = subprocess.run(gen_cmd, capture_output=True, text=True)
    assert gen_res.returncode == 0, f"Failed to generate testsrc: {gen_res.stderr}"
    assert test_src.exists() and test_src.stat().st_size > 0

    # 2. Initialize chunker with overlap enabled (chunk=6s, overlap=2s -> step=4s)
    output_dir = tmp_path / "stream_output"
    chunker = LiveStreamChunker(
        stream_url=str(test_src),
        output_dir=output_dir,
        chunk_seconds=6,
        overlap_seconds=2,
        max_offline_seconds=0,
        ffprobe_check=True,
    )

    # 3. Run chunker until stream file completes
    chunks = list(chunker.iter_completed_chunks())

    # 4. Verify chunks were successfully produced
    assert len(chunks) >= 2, f"Expected at least 2 overlapping chunks, got {len(chunks)}"

    for c in chunks:
        assert c.exists()
        assert c.stat().st_size > 0
        # Verify valid container with ffprobe
        assert chunker.validate_chunk_ffprobe(c) is True
