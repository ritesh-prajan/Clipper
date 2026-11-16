# Audit: live_stream_clipper.py & Clipper Architecture

Reviewed against `openshorts/app.py` endpoints, real FFmpeg command specifications, and Python best practices.

---

## Round 1: Initial Audit & Fixes

| # | Lines | Problem | Severity | Fix Applied |
|---|-------|---------|----------|-------------|
| a | 234 | `stderr=subprocess.PIPE` on FFmpeg Popen is never drained. Once the OS pipe buffer (~64 KB) fills, FFmpeg blocks forever — silent deadlock on any run > a few minutes. | Critical | Redirect stderr to a rotating log file via `open(log_path, "a")`, never PIPE. |
| b | 268-275 | When `ffmpeg_proc.poll()` returns non-None the main loop `break`s immediately before scanning `segments.txt` one final time. The last (often best) chunk is silently dropped. | Critical | `iter_completed_chunks` flushes segments after FFmpeg exit before returning. |
| c | 108-121 | `upload_file` calls `f.read()` for the PUT body — a 600s segment can be 1–3 GB, causing OOM. | Critical | Stream in 1 MB chunks via `httpx` with a generator. |
| d | 196-199 | `download_clip` reads the entire HTTP response body into RAM before writing to disk. Same OOM risk. | High | Stream response to disk: `for chunk in response.iter_bytes(1_048_576)`. |
| e | 93 | `slot_info.get("upload_url")` may return `None`; then `.startswith("http")` raises `AttributeError`. | Critical | Validate every required field from every API response; raise `UploadError` with the full response body if missing. |
| f | 160-165 | Calls `Popen(["ffmpeg", ...])` without checking `shutil.which("ffmpeg")`. Same for `streamlink`/`yt-dlp`. Results in cryptic `FileNotFoundError`. | High | Preflight check at startup using `shutil.which`; print OS-specific install hints and raise `RuntimeError`. |
| g | 72-78 | `test_connection` only logs a warning and the pipeline continues, then every subsequent API call fails. | High | Hard failure by default (raises `RuntimeError`); configurable retry loop with exponential backoff via `server_retry_max_attempts` and `server_retry_backoff`. |
| h | 234-240 | `save_manifest` writes directly to `manifest_file`; a crash mid-write corrupts the file and all state is lost. | High | Replaced by SQLite with WAL mode and atomic transactions. |
| i | 211-220 | Clip filenames derived from titles: Windows reserved names (`CON`, `NUL`…) not handled; path separators not stripped; collisions overwrite silently. | High | `uuid4()` prefix + sanitized title (re.sub, max 60 chars, strip reserved names). |
| j | 268 | `size > 100_000` decides a chunk is "done" but FFmpeg may still be writing at that point. | High | Validate with `ffprobe -v quiet -print_format json -show_format`; only yield if exit code is 0 and duration > 0. |
| k | 128-125 | Fixed `time.sleep(poll_interval)` with hard-coded 1200s max. 120 HTTP requests for a busy server; stalled jobs time out silently. | Medium | Exponential backoff (5s→60s). Log progress. Surface stalled jobs explicitly. |
| l | — | Chunk and clip files grow without bound. No disk-usage guard. | High | `max_disk_gb` config; delete oldest processed chunks before each upload if over limit. |
| m | 32, 71 | `api_key` stored as `self.api_key`; any repr/debug log exposes it. Error handler prints full URLs which may include auth tokens. | Medium | Store key only in a closure or custom `httpx.Auth`. Never log auth headers. |
| n | 44,62,70,110,164,174,196 | Broad `except Exception` swallows tracebacks including `KeyboardInterrupt`. | Medium | Narrow to specific exception types; log full traceback at DEBUG. |
| o | — | No type hints, no docstrings, no package structure, no tests. | Medium | Reorganised into `clipper/` package with full type hints, docstrings, `pyproject.toml`. |
| p | — | No stream reconnect / supervisor: pipeline terminates on first stream drop. | High | Supervisor loop with exponential backoff up to `max_offline_seconds`. |
| q | — | No persistent state: crash → re-processes all chunks, re-posts all clips. | High | SQLite state; on restart skip terminal-state chunks/jobs/clips. |
| r | — | No overlap between chunks: moments on boundaries are split and missed. | Medium | Continuous raw segmenting + FFmpeg stream copy concat windowing. |
| s | — | No publishing / approval / social posting support. | — | Added `clipper/publisher/` + `clipper/approval.py`. |

---

## Round 2: In-Depth Verification & Fixes

| # | Component | Problem Found | Severity | Fix Applied |
|---|-----------|---------------|----------|-------------|
| 1 | `clipper/recorder.py` | FFmpeg died immediately with `Unrecognized option 'segment_overlap'`. `-segment_overlap` does not exist in FFmpeg's `segment` muxer. | Critical | Removed invalid option. Implemented true overlap windowing: FFmpeg segments continuously into raw segments of duration `step = chunk_seconds - overlap_seconds`, and overlapping chunks of duration `chunk_seconds` are synthesized on completion using FFmpeg stream copy (`-c copy`) via temporary concat demuxer lists (`concat.txt`). |
| 2 | `clipper/recorder.py` | FFmpeg failed with `Option reconnect not found` when opening local files or non-HTTP inputs in test environments. | High | Restricted network reconnect options (`-reconnect 1 -reconnect_at_eof 1 ...`) strictly to URLs starting with `http://` or `https://`. |
| 3 | `tests/test_recorder.py` | Mock-only unit tests hid real FFmpeg argument syntax errors. | High | Added `test_real_ffmpeg_recording_with_overlap` which generates a real `lavfi testsrc` video with FFmpeg, records it with overlap enabled (`chunk_seconds=6, overlap_seconds=2`), and asserts valid chunks with real `ffprobe`. |
| 4 | `clipper/processor.py` | Global clip offset estimation needed exact alignment with synthesized overlapping chunks. | High | Updated offset calculation to `chunk_idx * effective_chunk_time` where `effective_chunk_time = max(1, chunk_seconds - overlap_seconds)`, aligning 1:1 with chunk start timestamps across stream boundaries. |
| 5 | `clipper/config.py` & `clipper/publisher/upload_post.py` | Lack of strict enforcement for copyright permission gate. | High | `check_copyright_permission(raise_on_error=True)` enforces ownership; `publisher.post()` strictly raises `PermissionError` if `i_own_or_have_permission` is false. `pipeline._publisher_loop()` refuses to publish while allowing clips to remain staged in `review/`. |
| 6 | `clipper/pipeline.py` | Server reachability was only logging a warning on startup. | Medium | Made server reachability a hard failure (`RuntimeError`) by default. Added configurable retry loop with exponential backoff via `server_retry_max_attempts` and `server_retry_backoff`. |
| 7 | `live_stream_clipper.py` | Legacy script was out of date with modern architecture. | Medium | Replaced `live_stream_clipper.py` with a thin, backward-compatible entry-point wrapper delegating to `clipper.pipeline:main`. |
| 8 | Repository hygiene | No `.gitignore` present; untracked caches, temporary files, outputs, and `.db` files appeared in status. | Low | Added comprehensive `.gitignore` covering `__pycache__`, `.pytest_cache`, `live_output/`, `*.db`, `config.yaml`, `.env`, and `openshorts/`. Cleaned up scratch scripts. |
| 9 | `clipper/publisher/upload_post.py` & `clipper/db.py` | `mark_clip_posted` was missing on `Database` causing multi-platform posting tracking to fail. | Medium | Added `mark_clip_posted(clip_id, platform)` in `Database` and hooked up post persistence. |
| 10 | `tests/test_e2e_pipeline.py` | Complete end-to-end dry run needed to verify all stages without external network dependencies. | High | Built an end-to-end integration test against a local fake OpenShorts HTTP server handling chunked streaming PUTs, verifying: `record -> chunk -> upload -> process -> clip in review -> approve -> post`. |

---

## API Field Verification (from openshorts/app.py — verified against source)

| Endpoint | Verified Request Fields | Verified Response Fields |
|----------|------------------------|--------------------------|
| `POST /api/uploads` | `{"filename": str}` JSON body | `upload_id`, `upload_url`, `method`, `max_mb`, `expires_in` |
| `PUT /api/uploads/{upload_id}` | Raw video bytes in body (streamed via chunked transfer encoding) | `upload_id`, `bytes`, `duration_seconds` |
| `POST /api/process` | `{"upload_id": str, "acknowledged": true, "output_format": str, "layouts": list}` JSON | `job_id`, `status` |
| `GET /api/status/{job_id}` | — | `status`, `logs`, `log_times`, `result.clips[].video_url`, `result.clips[].download_url`, `result.clips[].title`, `result.clips[].video_title_for_youtube_short`, `result.clips[].video_description_for_instagram`, `result.clips[].video_description_for_tiktok` |
| `POST /api/social/post` | `SocialPostRequest`: `job_id`, `clip_index`, `api_key`, `user_id`, `platforms`, `title`, `description`, `scheduled_date`, `timezone` | `request_id` (and other Upload-Post fields) |
| `GET /api/social/post-status/{request_id}` | — | `status`, `results[].platform`, `results[].success`, `results[].message` |
| `GET /api/social/user` | — | `profiles[].username`, `profiles[].connected` |

---

## Unverifiable Behaviours & Known Operational Notes

1. **`download_url` vs `video_url`**:
   - `download_url` is only present when `MEDIA_SECRET` is configured on the OpenShorts server.
   - On self-hosted OpenShorts without `MEDIA_SECRET`, only relative `video_url` is returned. The client handles both seamlessly by prepending `base_url` when `download_url` is absent.
2. **`SocialPostRequest.api_key`**:
   - In cloud mode, `api_key` in the request body is ignored. For self-hosted OpenShorts, `UPLOAD_POST_API_KEY` can be supplied via the request body or configured in the server's `.env`.
3. **Upload-Post Platform Authorization Expiry**:
   - Platform tokens (especially TikTok) may expire periodically on the Upload-Post provider side. The pipeline detects authorization errors and isolates them so failures on one platform never abort posting to healthy platforms (e.g., YouTube Shorts or Instagram Reels).
