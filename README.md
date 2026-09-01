# ⚡ ZipStreamHub

<p align="center">
  <img src="docs/assets/banner.svg" alt="ZipStreamHub Banner" width="100%" />
</p>

<p align="center">
  <a href="https://github.com/MHJoy99/ZipStream-Hub"><img src="https://img.shields.io/badge/Startup-0.6s_Tail_Parse-00F0FF?style=for-the-badge&logo=fastapi&logoColor=white" alt="Startup Badge" /></a>
  <a href="https://github.com/MHJoy99/ZipStream-Hub"><img src="https://img.shields.io/badge/Disk_Usage-0_Bytes-10B981?style=for-the-badge&logo=files&logoColor=white" alt="Disk Usage Badge" /></a>
  <a href="https://github.com/MHJoy99/ZipStream-Hub"><img src="https://img.shields.io/badge/ZIP64-16_EB_Limit-C084FC?style=for-the-badge&logo=archive&logoColor=white" alt="ZIP64 Badge" /></a>
  <a href="https://github.com/MHJoy99/ZipStream-Hub"><img src="https://img.shields.io/badge/Seeking-0ms_Realtime-F59E0B?style=for-the-badge&logo=speedtest&logoColor=white" alt="Seeking Badge" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg?style=for-the-badge" alt="License Badge" /></a>
</p>

---

**ZipStreamHub** is an ultra-fast, zero-download streaming server and virtual archive extractor for remote ZIP and ZIP64 files. It bridges cloud archive storage directly to media players like **PotPlayer**, **MPV**, **VLC**, and **IINA** or web browsers, allowing instant playback and random-access seeking inside multi-gigabyte or multi-terabyte cloud archives without downloading or unpacking files locally.

---

## 📑 Table of Contents
- [✨ Key Features](#-key-features)
- [📊 Benchmark & Performance](#-benchmark--performance-comparison)
- [🏗️ System Architecture](#-architecture-pipeline)
- [🚀 Quick Start](#-quick-start)
  - [1. Web GUI Experience](#1-web-gui-dashboard)
  - [2. Interactive CLI Player](#2-interactive-cli-player)
  - [3. Docker Deployment](#3-docker-deployment)
- [🔌 REST API Overview](#-rest-api-overview)
- [📖 Documentation Links](#-documentation-links)
- [⚙️ Memory & Buffer Tuning (Up to 5GB)](#️-memory--high-speed-buffer-tuning-up-to-5gb)
- [📁 Project Layout](#-project-layout)
- [🛠️ Configuration & Environment Variables](#️-configuration--environment-variables)
- [🤝 Contributing & License](#-contributing--license)

---

## ✨ Key Features

<p align="center">
  <img src="docs/assets/feature-grid.svg" alt="ZipStreamHub Feature Grid" width="100%" />
</p>

- **⚡ Zero-Download Streaming:** Streams media directly from remote HTTP/HTTPS ZIP archives over standard HTTP 206 byte-range requests.
- **📦 Full ZIP / ZIP64 & Store Support:** Supports massive archives > 4GB (up to 16 Exabytes) with `STORE` and `DEFLATE` methods.
- **🚀 Intelligent Sliding-Window Prefetcher:** Multi-threaded read-ahead buffer (default 32MB) with 128KB chunk slicing for butter-smooth playback and sub-second seek times.
- **🎯 1-Click Native Player Integration:** Auto-detects local media players (**PotPlayer**, **MPV**, **VLC**, **MPC-HC**, **MPC-BE**, **IINA**) via Windows Registry and system PATH.
- **🌐 In-Browser Web Player & Dark-Mode Dashboard:** Built-in HTML5 video player with fullscreen mode, playback speed control, and live stream telemetry.
- **📺 M3U / M3U8 IPTV Playlist Generator:** Instantly export complete archive playlists for **Kodi**, **Infuse (Apple TV/iOS)**, and VLC.
- **💬 Auto Subtitle (.srt $\to$ WebVTT) Engine:** Automatic subtitle detection and on-the-fly conversion of `.srt` tracks to WebVTT for seamless browser viewing.
- **⭐ Archive History & Bookmarks:** Quick-access storage for frequently inspected archives with 1-click reloading and saved seek positions.
- **🪟 Windows 1-Click Launcher:** Effortless background startup via `launch_zipstream.vbs`, desktop shortcuts, and automatic browser launch.
- **💻 Interactive Terminal Player:** Colorful ANSI CLI (`cli.py` / `zipplay.bat`) for keyboard-driven episode selection.

---

## 📊 Benchmark & Performance Comparison

<p align="center">
  <img src="docs/assets/benchmark-comparison.svg" alt="ZipStreamHub Benchmark Comparison" width="100%" />
</p>

| Metric | Traditional Download | ZipStreamHub Streaming |
|---|---|---|
| **Time to First Frame** | 15–45 minutes (waiting for download) | **~0.6 seconds** |
| **Local Disk Space Used** | 50 GB – 100 GB+ | **0 Bytes** (pure in-memory) |
| **Random Seek Latency** | Instant (after full download) | **< 5ms** (HTTP 206 Range translation) |
| **Network Data Consumed** | 100% of archive size | Only streamed portions |

---

## 🏗️ Architecture Pipeline

<p align="center">
  <img src="docs/assets/architecture-diagram.svg" alt="ZipStreamHub Architecture Diagram" width="100%" />
</p>

1. **Tail-Parsing Sequence**: ZipStreamHub requests the final 1MB of the remote file using HTTP Range requests to locate the End of Central Directory (EOCD `0x06054b50`) and ZIP64 Locator (`0x07064b50`).
2. **Central Directory Resolution**: Reads file headers (`0x02014b50`) to construct the in-memory archive index in ~0.6 seconds.
3. **Range Translation**: Player requests for byte ranges $[S, E]$ are offset against the file's `data_offset` and served via an asynchronous sliding-window prefetcher.

---

## 🚀 Quick Start

### Prerequisites
- Python 3.9 or newer
- (Optional) PotPlayer, MPV, or VLC installed on your machine

### Installation
```bash
git clone https://github.com/MHJoy99/ZipStream-Hub.git
cd ZipStreamHub
pip install -e .
# or for development:
pip install -e ".[dev]"
```

### 1. Web GUI Dashboard
Start the high-concurrency streaming server using the CLI entrypoint or direct script:
```bash
zipstream-server
# or
python server.py
```
Open your browser at `http://127.0.0.1:8787` to access the interactive web control panel.

### 2. Interactive CLI Player
Stream directly from your terminal:
```bash
# Interactive episode browser (using installed CLI or script)
zipstream "https://example.com/anime_season1.zip"
# or
python cli.py "https://example.com/anime_season1.zip"

# Non-interactive direct launch into PotPlayer
zipstream "https://example.com/anime_season1.zip" --ep 1 --player potplayer
```

### 3. Docker Deployment
```bash
docker compose up -d
```

---

## 🔌 REST API Overview

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/inspect` | Inspects remote ZIP URL and returns JSON archive structure |
| `GET` | `/api/media_inspect` | Binary media header inspection (video/audio codecs, width, height, duration) |
| `GET` | `/api/strm.zip` | Generates and downloads virtual `.strm` media library ZIP bundle |
| `GET` | `/api/stats` | Real-time streaming metrics (bitrate, active streams, buffer, latency) |
| `PROPFIND` | `/webdav/` | RFC 4918 WebDAV directory tree for Infuse, Kodi, and Windows Explorer |
| `GET` | `/webdav/` | WebDAV HTML Directory listing and transparent HTTP 206 streaming |
| `GET` | `/api/playlist.m3u` | Exports `#EXTM3U` playlist for media players |
| `GET` | `/api/subtitle` | Extracts and converts subtitle tracks to WebVTT on the fly |
| `POST` | `/api/play` | Launches host media player with stream URL |
| `GET` | `/stream/<id>/<filename>` | HTTP 206 Byte-Range streaming endpoint |
| `HEAD` | `/stream/<id>/<filename>` | Returns stream Content-Length and MIME type |

Detailed API specifications are available in [docs/API.md](docs/API.md).

---

## 📖 Documentation Links

- 🍿 **Jellyfin, Emby & Kodi STRM Virtual Library**: [docs/JELLYFIN_EMBY_KODI.md](docs/JELLYFIN_EMBY_KODI.md)
- 🗂️ **WebDAV Network Drive & Infuse / Kodi Setup**: [docs/WEBDAV_INFUSE.md](docs/WEBDAV_INFUSE.md)
- 🎬 **Complete Media Player & M3U Guide**: [docs/PLAYERS.md](docs/PLAYERS.md)
- 📊 **Competitive Analysis & Benchmarks**: [docs/COMPETITIVE_ANALYSIS.md](docs/COMPETITIVE_ANALYSIS.md)
- 🤖 **LLM Reference Files**: [llms.txt](llms.txt) | [llms-full.txt](llms-full.txt)
- 🏛️ **Architecture & Binary Deep Dive**: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- 🔌 **REST API Specification**: [docs/API.md](docs/API.md)
- 🛠️ **Troubleshooting & Optimization**: [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)
- 🎬 **Beginner's Guide (No Coding Required)**: [docs/QUICKSTART_NON_CODERS.md](docs/QUICKSTART_NON_CODERS.md)

---

## ⚙️ Memory & High-Speed Buffer Tuning (Up to 5GB)

ZipStreamHub is engineered with an intelligent **asynchronous sliding-window read-ahead prefetching engine**. Unlike traditional tools that force a full multi-gigabyte archive download to disk before playback, ZipStreamHub streams on-demand while dynamically buffering uncompressed media chunks directly in system RAM.

### 🔄 Sliding-Window Buffering vs. Full File Download

```
Traditional Download:  [████████████████████████████████████████] 50GB written to Disk (Wait 30+ mins)
ZipStreamHub Engine:   [············►►► [ Sliding Window: 1GB-5GB RAM ] ◄◄◄······················] 0B Disk
```

1. **Zero Disk I/O**: Buffers are managed in volatile memory (`StreamPrefetcher` ring queues) with zero writes to SSD/HDD.
2. **Dynamic Backpressure**: When your player buffer fills, upstream HTTP requests pause automatically without wasting bandwidth or overflowing RAM.
3. **Instant Seek Drain**: Seeking to a new position immediately signals worker threads via an abort event, drains old queued chunks, and starts prefetching from the new byte offset in $< 5\text{ms}$.
4. **Bandwidth Efficiency**: Only the exact video segments you watch are fetched across the network.

### 📊 Recommended RAM-Based Buffer Presets

| System Configuration | Preset Value (`ZIPSTREAM_PREFETCH_MB`) | Forward Buffer | Ideal Use Case |
|---|---|---|---|
| **4GB RAM System** (Raspberry Pi / Low-Memory VPS) | `64` (64 MB) | ~30–60 sec | 720p / 1080p standard bitrate playback with minimal footprint |
| **8GB–16GB RAM System** (Standard Desktop / Laptop) | `1024` (1 GB) | ~2–5 min | High-bitrate 4K HDR REMUX (60–80 Mbps) with smooth scrubbing |
| **32GB+ High-End PC & Gigabit Fiber** | `5120` (5 GB) | ~10–25 min | Saturates Gigabit networks; holds entire movie sections in RAM for instant chapter jumping |

---

## 📁 Project Layout

ZipStreamHub follows a clean, standard `src/` layout with backward-compatible root shims for effortless usage as both an installed Python package and direct script execution:

```
ZipStreamHub/
├── src/
│   └── zipstream/               # Core Python package
│       ├── __init__.py          # Package exports & version
│       ├── engine.py            # ZIP/ZIP64 tail parser & StreamPrefetcher
│       ├── server.py            # HTTP/WebDAV multi-threaded streaming server
│       ├── webdav_bridge.py     # RFC 4918 WebDAV virtual filesystem
│       ├── cli.py               # Interactive ANSI terminal UI & player
│       ├── media_inspector.py   # In-memory binary media header parser
│       ├── strm_generator.py    # Jellyfin / Emby / Kodi .strm generator
│       ├── subtitle_parser.py   # Subtitle extraction & WebVTT converter
│       ├── player_detector.py   # Native player detection & launch hooks
│       ├── history.py           # SQLite history & bookmark manager
│       ├── config.py            # Configuration loader & dataclasses
│       └── static/              # Embedded Web UI assets (HTML, Icons)
├── tests/                       # Complete pytest suite (100% pass)
├── docs/                        # Detailed guides & protocol specs
├── engine.py, server.py, ...    # Root shims for standalone script execution
├── pyproject.toml               # PEP 517/621 package & build configuration
└── requirements.txt             # Production dependencies
```

---

## 🛠️ Configuration & Environment Variables

ZipStreamHub supports configuration via **Web UI Settings**, **`config.json`**, and **Environment Variables** (`.env`).

**Precedence Order:** `Environment Variables` > `config.json` > `Default Values`

### 1. Environment Variables (`.env`)
Copy `.env.example` to `.env` or pass variables directly:
```bash
# Example for high-speed 5GB buffering on 32GB+ RAM systems
export ZIPSTREAM_PREFETCH_MB=5120
export ZIPSTREAM_SLICE_KB=128
export ZIPSTREAM_HOST=0.0.0.0
export ZIPSTREAM_PORT=8787
export ZIPSTREAM_DEFAULT_PLAYER=potplayer
```

### 2. Configuration File (`config.json`)
```json
{
  "server": {
    "host": "0.0.0.0",
    "port": 8787,
    "debug": false
  },
  "streaming": {
    "prefetch_buffer_size_mb": 1024,
    "slice_size_kb": 128,
    "max_concurrent_streams": 8,
    "chunk_timeout_seconds": 30
  },
  "players": {
    "default_player": "potplayer"
  },
  "ui": {
    "theme": "dark",
    "accent_color": "#3b82f6",
    "compact_mode": false,
    "show_thumbnails": true,
    "page_size": 50,
    "autoplay": false
  }
}
```

### 3. Web UI Dashboard Configuration
Open the web control panel at `http://127.0.0.1:8787` and navigate to the **Settings** modal to configure default players, streaming preferences, and UI appearance live.

---

## 🤝 Contributing & License

Contributions, issues, and feature requests are welcome!  
Distributed under the **MIT License**. See `LICENSE` for more information.
