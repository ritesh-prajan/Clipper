# Live Stream AI Clipper with OpenShorts

Automated pipeline to ingest active live streams (Twitch, YouTube, Kick), segment them into rolling chunks with overlap without CPU overhead, and feed them into **[OpenShorts](https://github.com/mutonby/openshorts)** to generate vertical 9:16 viral shorts in near real-time, stage them for review, and auto-post them.

---

## 🛠️ Architecture

```
[ Active Live Stream (Twitch / YouTube / Kick) ]
                     │
                     ▼ (Streamlink / yt-dlp)
            [ Direct Video Stream ]
                     │
                     ▼ (FFmpeg segment muxer + stream copy overlap)
            [ Rolling Chunks with Overlap (e.g. 10m each, 20s overlap) ]
                     │
                     ▼ (clipper worker pool + SQLite queue)
          [ OpenShorts API (/api/uploads & /api/process) ]
                     │
         ┌───────────┴───────────┐
         ▼                       ▼
 [ Faster-Whisper ASR ]  [ Google Gemini Flash ]
 (Word timestamps)       (Viral moment & hook detection)
         │                       │
         └───────────┬───────────┘
                     ▼
          [ YOLOv8 & MediaPipe Auto-Framing ]
          (Smart 9:16 vertical crop / dual-speaker stack)
                     │
                     ▼
             [ FFmpeg Assembly ]
             (Burned-in dynamic animated captions)
                     │
                     ▼
         📁 live_output/review/  <─── Web Review Dashboard (http://localhost:8765)
                     │
                     ▼ (Approved)
         📁 live_output/shorts/  ───► Social Publishing (YouTube Shorts, IG Reels, TikTok)
```

---

## 🚀 Setup & Prerequisites

### 1. Install Stream Ingestion Tools

You need **FFmpeg** and **Streamlink** (or `yt-dlp`):

#### On Windows (PowerShell):
```powershell
# Install FFmpeg
winget install Gyan.FFmpeg

# Install streamlink & yt-dlp
python -m pip install streamlink yt-dlp
```

---

### 2. Run OpenShorts

You can use either a **Local Instance (Free & Self-hosted)** or the **OpenShorts Cloud**:

#### Choice A: Self-Hosted with Docker
Open a terminal in the cloned `openshorts` folder:
```bash
cd openshorts
cp .env.example .env
# Edit .env and paste your GEMINI_API_KEY (from https://aistudio.google.com/app/apikey)
docker compose up
```
*OpenShorts will be live at `http://localhost:8000` (API) and `http://localhost:5175` (Dashboard).*

#### Choice B: OpenShorts Cloud
If you don't want to run Docker on your machine, grab an API key from [openshorts.app](https://www.openshorts.app):
```powershell
$env:OPENSHORTS_API_KEY = "osk_your_api_key_here"
```

---

## 🎬 How to Run the Live Clipper

You can run the modern package directly via `python -m clipper` or via the backward-compatible `live_stream_clipper.py` wrapper:

### Example 1: Standard Run with config.yaml
```powershell
python -m clipper
# or
python live_stream_clipper.py
```

### Example 2: Override Stream URL via CLI
```powershell
python -m clipper --stream-url "https://twitch.tv/shroud"
```

### Example 3: Auto-approve Mode
```powershell
python -m clipper --stream-url "https://twitch.tv/shroud" --auto-approve
```

### Example 4: Dry-Run Mode
```powershell
python -m clipper --dry-run
```

### Example 5: Pipeline Status
```powershell
python -m clipper --status
```
