# Clipper Studio (`clipper/`)

**Production-grade local-first AI video clipper and multi-account social publisher built on top of [OpenShorts](https://github.com/mutonby/openshorts).**

Captures live streams and video files in rolling overlapping chunks → uploads to OpenShorts AI (Whisper ASR + YOLO face tracking + Gemini viral moment detection) → extracts vertical 9:16 shorts → stages clips for review → auto-publishes to YouTube Shorts, Instagram Reels, and TikTok across **multiple accounts** with rate limits and spam protection.

---

## Table of Contents

1. [Architecture & Web Studio Overview](#1-architecture--web-studio-overview)
2. [Windows Setup & Prerequisites](#2-windows-setup--prerequisites)
3. [Running OpenShorts](#3-running-openshorts)
4. [Starting the Web Studio](#4-starting-the-web-studio)
5. [Adding Multiple Accounts](#5-adding-multiple-accounts)
6. [First-Run Checklist (Dry Run & Verification)](#6-first-run-checklist-dry-run--verification)
7. [Studio Pages & Features](#7-studio-pages--features)
8. [Docker Compose Full Stack](#8-docker-compose-full-stack)
9. [CLI Reference](#9-cli-reference)
10. [Known Limitations](#10-known-limitations)

---

## 1. Architecture & Web Studio Overview

```
Browser (React + Vite + Tailwind Dark UI)
  │   ▲  HTTP REST + Server-Sent Events (SSE)
  ▼   │
FastAPI Backend (clipper/web/ :8080)
  ├── SQLite Database (WAL mode, atomic transactions, idempotency key)
  ├── Fernet Key Encryption (AES-128-CBC + HMAC-SHA256 at rest)
  ├── Source Worker Manager (isolated pipeline threads per stream)
  ├── Clip Processor (rolling chunks, deduplication, Gemini spend cap guard)
  ├── Publishing Fan-Out (multi-account dispatch, jitter, daily limits, cooldown)
  └── Range-Request Video Streaming (HTTP 206, no RAM buffering)
        │
        ├── OpenShorts Server (:8000) (Whisper + YOLO + Gemini)
        └── Upload-Post API (YouTube Shorts, Instagram Reels, TikTok)
```

---

## 2. Windows Setup & Prerequisites

### 1. Install FFmpeg
FFmpeg is required for continuous stream segmenting, keyframe alignment, and overlap synthesizing.

In PowerShell (Run as Administrator):
```powershell
winget install Gyan.FFmpeg
```
Restart PowerShell and verify:
```powershell
ffmpeg -version
ffprobe -version
```

### 2. Install Stream Resolvers
Install `streamlink` (best for Twitch/Kick) and `yt-dlp` (required for YouTube streams and videos):
```powershell
pip install streamlink yt-dlp
```
Verify:
```powershell
yt-dlp --version
streamlink --version
```

### 3. Install Python Dependencies
From the repository root:
```powershell
pip install -r requirements.txt
```

### 4. (Optional) Build Frontend from Source
The repository includes a pre-built React frontend bundle in `clipper/web/static/`. If you want to modify the frontend UI:
```powershell
cd frontend
npm install
npm run build
cd ..
```
This compiles the TypeScript SPA directly into `clipper/web/static/`.

---

## 3. Running OpenShorts

Clipper connects to an OpenShorts backend instance (default: `http://localhost:8000`).

### Running OpenShorts via Docker in WSL2 / Linux
```bash
cd openshorts
# Ensure GEMINI_API_KEY is present in .env
docker compose up -d backend frontend
```
Verify the server is healthy:
```powershell
curl http://localhost:8000/health
# Returns: {"status": "ready"}
```

---

## 4. Starting the Web Studio

Start the web studio with a single command:

```powershell
python -m clipper.web
```
By default, the studio binds to `http://127.0.0.1:8080`. Open that URL in your browser!

### CLI Options for Web Studio
```powershell
# Custom port and host:
python -m clipper.web --host 127.0.0.1 --port 8080

# Enable single-user password protection (required for non-localhost):
python -m clipper.web --host 0.0.0.0 --port 8080 --password "MySecretPass123"

# Custom output directory:
python -m clipper.web --output-dir "D:/ClipperOutput"
```

---

## 5. Adding Multiple Accounts

Clipper supports publishing to multiple YouTube, Instagram, and TikTok channels from a single dashboard.

### How Credentials and Profiles Work
OpenShorts and Upload-Post support two multi-account models:
1. **Multiple Profiles under One API Key**: If your Upload-Post account has multiple social profiles (e.g., `@gaming_shorts` and `@tech_clips`), add two accounts in Clipper with the same API key and specify the respective **Profile Username** (`user_id`).
2. **Multiple Distinct API Keys**: If you manage different Upload-Post accounts, enter each API key into its own account.

### Encryption & Privacy
- **Encrypted at Rest**: Every API key is encrypted using Fernet symmetric encryption before being written to SQLite. The encryption key is loaded from `CLIPPER_SECRET_KEY` or stored in `.clipper_keyfile` (gitignored).
- **Masked in UI & API**: Keys are never returned in plain text. Responses only display `••••••••{last4}`.
- **Never Logged**: The logging subsystem automatically redacts all configured keys.

### Independent Platform Safeguards
- **TikTok Regional / Authorization Isolation**: If TikTok fails or is unavailable in your region, **it does not block YouTube or Instagram**. The error is captured per-platform and the remaining platforms publish successfully.
- **Per-Platform Daily Limits**: Configure max posts per 24 hours per platform (e.g. 5 on YouTube, 10 on Instagram).
- **Minimum Gap Cooldown**: Prevents back-to-back posting (default: 300 seconds).
- **Staggering Jitter**: Applies random delays between accounts to prevent platform spam flags.
- **Caption Variations**: Configure custom hashtag suffixes per account (e.g. `#Gaming` vs `#Tech`).

### Testing Connection
On the **Social Accounts** page, click **Test Connection** next to any account. Clipper queries OpenShorts `GET /api/social/user` and displays which social networks are actively authenticated, flagging any tokens that have expired.

---

## 6. First-Run Checklist (Dry Run & Verification)

Before posting live clips to social networks, follow this safety checklist:

- [ ] **1. Enable Dry Run Mode**:
  Navigate to **Settings** and ensure **Dry Run Mode** is checked. In dry run mode, all pipeline stages run, but posts are logged and simulated without hitting external social APIs.
- [ ] **2. Check Gemini Spend Cap**:
  In **Settings**, set a conservative spend cap (e.g. `$5.00` or `$10.00`). If your stream runs longer than anticipated, Clipper automatically halts chunk submission once the ceiling is reached.
- [ ] **3. Add Social Account**:
  Navigate to **Social Accounts**, click **Add Account**, paste your Upload-Post API key, select your platforms, and click **Test Connection**.
- [ ] **4. Add Stream Source & Confirm Rights**:
  Navigate to **Streams & Sources**, click **Add Source**. Paste your stream URL or upload a test video. **Check the box "I own or have permission to use this content"**.
- [ ] **5. Start Pipeline & Monitor Logs**:
  Click **Start Pipeline**. Open **Live Logs** to watch FFmpeg chunking and OpenShorts AI moment detection in real time.
- [ ] **6. Review Clips in Gallery**:
  Navigate to **Clips Gallery**. Watch the vertical 9:16 video previews. Edit titles or hashtags as desired. Click **Approve**.
- [ ] **7. Verify Publishing Queue**:
  Navigate to **Publishing Queue**. Verify that simulated post entries appear with status `dry_run`.
- [ ] **8. Go Live**:
  Once satisfied, uncheck **Dry Run Mode** in **Settings**. Future approved clips will publish directly!

---

## 7. Studio Pages & Features

### 1. Dashboard (`/`)
- Live stream status cards (Recording / Processing / Idle / Stopped).
- Aggregated counters: Chunks sliced, clips generated, posts published today.
- Visual disk capacity meter with auto-pruning warnings.
- Real-time Gemini spend tracker with persistent spend cap banner.

### 2. Streams & Sources (`/sources`)
- Add stream URLs (YouTube Live, Twitch, Kick, RTMP) or upload local video files.
- Customize chunk length (e.g. 90s) and overlap window (e.g. 15s).
- Mandatory ownership gate toggle.
- Start / Stop / Delete controls for concurrent pipeline workers.

### 3. Clips Gallery (`/clips`)
- OpusClip-style 9:16 vertical video cards.
- Streaming video player with scrubbing (HTTP 206 range requests).
- AI virality score badge (e.g. 9.4/10) if returned by OpenShorts.
- Inline title and caption editor.
- 1-click Approve, Reject, and Bulk Actions.
- Target accounts destination picker.

### 4. Social Accounts (`/accounts`)
- Add and edit target accounts for YouTube Shorts, Instagram Reels, and TikTok.
- Masked encrypted credentials.
- 1-click connection testing and token expiration diagnosis.
- Per-account custom hashtag suffixes and rate limit controls.

### 5. Publishing Queue (`/publishing`)
- Live ledger of all posting dispatches keyed by `(clip_id, account_id, platform)`.
- Status indicators: `posted`, `pending`, `scheduled`, `failed`, `cooldown`, `dry_run`.
- Detailed error messages and 1-click **Retry** button for failed jobs.
- Clear warnings against duplicate simultaneous posting across accounts.

### 6. Live Logs Console (`/logs`)
- Real-time streaming log feed via Server-Sent Events (SSE).
- Auto-scroll lock toggle.
- Filter by log level (`INFO`, `WARNING`, `ERROR`) or keyword search.
- Automatic secret redaction for API keys and tokens.

### 7. Pipeline Settings (`/settings`)
- OpenShorts REST API base URL configuration.
- Max disk capacity ceiling in GB.
- Gemini API spend cap with automatic worker pausing.
- Global auto-approve toggle.
- Single-user password login setup.

---

## 8. Docker Compose Full Stack

To run OpenShorts and Clipper Web Studio together in Docker:

```bash
# 1. Set environment variables
export GEMINI_API_KEY="your_gemini_api_key"
export UPLOAD_POST_API_KEY="your_upload_post_api_key"

# 2. Build and start both containers
docker compose up --build -d
```

- OpenShorts Backend: `http://localhost:8000`
- Clipper Web Studio: `http://localhost:8080`

---

## 9. CLI Reference

The existing command-line interface continues to work seamlessly:

```bash
# Check status of chunks and review queue:
python -m clipper --status

# Run stream recording via CLI:
python -m clipper --stream-url "https://youtu.be/..."

# Run with auto-approval (skip review):
python -m clipper --stream-url "https://youtu.be/..." --auto-approve

# Run in dry-run mode:
python -m clipper --stream-url "https://youtu.be/..." --dry-run
```

---

## 10. Known Limitations

1. **WSL2 Docker Sleep Timeout**:
   On Windows, if WSL2 has no foreground process running, the WSL virtual machine may enter an idle sleep state after several minutes. For long unattended stream clipping sessions, keep a PowerShell window open or run the WSL keepalive task.
2. **TikTok Draft Mode**:
   By default, OpenShorts sends videos to TikTok in `MEDIA_UPLOAD` mode, which creates TikTok Drafts in the creator's TikTok mobile app rather than direct instant public publishing. Direct public posting requires a verified ByteDance TikTok Commercial API application.
3. **OpenShorts Minimum Chunk Duration**:
   OpenShorts moment detection algorithms require video segments of at least 45 seconds to perform reliable Whisper speech recognition and scene detection. We recommend setting chunk length to 90 seconds with 15–20 seconds overlap.
4. **Hardware Acceleration**:
   On CPU-only machines, transcribing audio and detecting faces with YOLO takes ~3–5 minutes per 90-second chunk. Running on an NVIDIA GPU (CUDA) reduces this to under 45 seconds per chunk.
