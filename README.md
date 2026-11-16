# Live Stream Clipper (`clipper/`)

Production-grade live-stream-to-viral-clips pipeline built on top of [OpenShorts](https://github.com/mutonby/openshorts).

Captures a live stream in rolling chunks → uploads to OpenShorts AI → extracts viral 9:16 shorts → stages for review → publishes to social networks.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Run OpenShorts](#2-run-openshorts)
3. [Connect social accounts](#3-connect-social-accounts)
4. [Configure clipper](#4-configure-clipper)
5. [Run the pipeline](#5-run-the-pipeline)
6. [Approval workflow](#6-approval-workflow)
7. [CLI reference](#7-cli-reference)
8. [Troubleshooting](#8-troubleshooting)

---

## 1. Prerequisites

Install the following system tools before running the pipeline.

### FFmpeg

FFmpeg is required for stream segmentation.

| Platform | Command |
|---|---|
| **Windows** | `winget install Gyan.FFmpeg` |
| **macOS** | `brew install ffmpeg` |
| **Linux (Debian/Ubuntu)** | `sudo apt install ffmpeg` |

### streamlink (recommended for Twitch/Kick)

| Platform | Command |
|---|---|
| **All** | `pip install streamlink` |

### yt-dlp (required for YouTube live, fallback)

| Platform | Command |
|---|---|
| **All** | `pip install yt-dlp` |

> At least one of `streamlink` or `yt-dlp` must be installed. The pipeline will refuse to start and print clear instructions if both are absent.

### Python packages

```bash
pip install -r requirements.txt
# or in editable mode:
pip install -e ".[dev]"
```

---

## 2. Run OpenShorts

OpenShorts must be running to process chunks. The easiest way is Docker Compose:

```bash
cd openshorts
cp .env.example .env
# Optional: add your Gemini API key to .env:
# echo "GEMINI_API_KEY=AIza..." >> .env
docker compose up --build
```

The OpenShorts API will be available at `http://localhost:8000`.  
The dashboard will be at `http://localhost:5175`.

> **Cloud**: If you use [openshorts.app](https://www.openshorts.app/), set `openshorts_url: https://api.openshorts.app` and add your `osk_...` API key to the config.

---

## 3. Connect social accounts

The pipeline uses the **Upload-Post** relay (via OpenShorts `/api/social/post`) to publish to TikTok, Instagram Reels, and YouTube Shorts from one place.

1. Register at [app.upload-post.com](https://app.upload-post.com/login)
2. Connect TikTok, Instagram, and/or YouTube under **Manage Users**
3. Generate an API key at [API Keys](https://app.upload-post.com/api-keys)
4. Enter the key in the OpenShorts dashboard under **Settings → Upload-Post**  
   *or* set it in `config.yaml` as `upload_post_api_key`

---

## 4. Configure clipper

Copy the example configuration and edit it:

```bash
cp config.example.yaml config.yaml
```

**Minimum required fields:**

```yaml
stream_urls:
  - "https://twitch.tv/YOUR_CHANNEL"   # or YouTube/Kick/RTMP URL

i_own_or_have_permission: true          # required; affirms rights to process content

openshorts_url: "http://localhost:8000"

platforms:
  - "upload_post"

upload_post_api_key: "your-upload-post-key"
```

See [config.example.yaml](config.example.yaml) for all options with inline documentation.

---

## 5. Run the pipeline

```bash
# Standard run with config.yaml in the current directory
python -m clipper

# Specify a config file
python -m clipper --config path/to/config.yaml

# Override the stream URL on the command line
python -m clipper --stream-url https://twitch.tv/my_channel

# Approve and publish all clips automatically (skip review dashboard)
python -m clipper --auto-approve

# Simulate without calling OpenShorts or social APIs
python -m clipper --dry-run

# Check pipeline status (queue depths, counts)
python -m clipper --status
```

The pipeline prints a **copyright warning** on first run if `i_own_or_have_permission` is not set to `true`.

---

## 6. Approval workflow

### Manual review (default: `auto_approve: false`)

When a chunk is processed and clips are extracted:

1. Clips are placed in `live_output/review/`
2. A review dashboard is served at **[http://localhost:8765](http://localhost:8765)**
3. Open the dashboard to preview each clip (inline `<video>` player)
4. Click **Approve & Publish** to approve the clip (or edit the title first)
5. Click **Reject** to discard the clip

Approved clips are moved to `live_output/shorts/` and published to configured social platforms.

### Auto-approve (`auto_approve: true`)

Clips skip the review queue and are published immediately after extraction. Use with caution on live streams.

---

## 7. CLI reference

```
python -m clipper [OPTIONS]

Options:
  --config, -c PATH     Path to YAML config file (default: config.yaml)
  --status              Print queue/processed/posted/failed counts and exit
  --stream-url, -u URL  Override stream URL from config
  --auto-approve        Automatically approve all generated clips
  --dry-run             Simulate pipeline (no uploads, no posts)
  --output-dir, -o DIR  Override output directory
```

---

## 8. Troubleshooting

### Stream drops / FFmpeg restarts

The recorder supervisor automatically retries with exponential backoff (1 s → 60 s) for up to `max_offline_seconds` (default: 3600 s = 1 hour). Check `live_output/chunks/ffmpeg_recorder.log` for FFmpeg errors.

### "Cannot reach OpenShorts" warning

Ensure `docker compose up` is running in the `openshorts/` directory, or set `openshorts_url` to the correct host. The pipeline continues recording even when OpenShorts is temporarily unreachable; queued chunks will be processed when connectivity is restored.

### Auth errors (social posting)

- Check that your Upload-Post API key is correctly set.
- Visit the OpenShorts dashboard at `http://localhost:5175` → **Settings** to verify the Upload-Post connection.
- Use `python -m clipper --dry-run` to verify config without hitting APIs.

### TikTok not available / TikTok failure

TikTok errors are isolated: a TikTok failure does **not** block posting to YouTube or Instagram. TikTok posts may fail due to account authorization expiry. Reconnect TikTok in the Upload-Post dashboard and retry.

### Clips overlap or duplicate

Clips with >50% temporal overlap across adjacent chunks are automatically deduplicated. If you still see duplicates, reduce `overlap_seconds` in the config.

### Disk space growing

Increase `max_disk_gb` or enable `cleanup_chunks: true` to delete raw chunks after extraction. The pipeline enforces the disk limit automatically, pruning oldest processed chunks when the threshold is reached.

### "Port 8765 already in use"

Another process is using the approval server port. Stop it, or the approval server will silently fail to start (manual review will not be available until the port is free).
