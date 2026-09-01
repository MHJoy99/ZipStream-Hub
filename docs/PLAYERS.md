# 🎬 Complete Media Player Streaming & M3U Guide

**ZipStreamHub** converts remote ZIP and ZIP64 archives into high-performance, seekable HTTP 206 byte-range media streams. This guide covers direct streaming, M3U/M3U8 playlist integration, and optimal player configurations for all major media players on Windows, macOS, Linux, iOS, and Android / Apple TV.

---

## 📑 Table of Contents
1. [Stream URL Structure & M3U Format](#-stream-url-structure--m3u-format)
2. [Daum PotPlayer (Windows)](#-daum-potplayer-windows)
3. [VLC Media Player (Cross-Platform)](#-vlc-media-player-cross-platform)
4. [MPV Player (Windows / macOS / Linux)](#-mpv-player-windows--macos--linux)
5. [MPC-HC & MPC-BE (Windows)](#-mpc-hc--mpc-be-windows)
6. [Kodi (Home Theater / Android TV / Fire TV)](#-kodi-home-theater--android-tv--fire-tv)
7. [Infuse (Apple TV / iOS / macOS)](#-infuse-apple-tv--ios--macos)
8. [IINA (macOS)](#-iina-macos)
9. [Subtitles & WebVTT Auto-Conversion](#-subtitles--webvtt-auto-conversion)
10. [LAN & Remote Network Streaming](#-lan--remote-network-streaming)

---

## 🌐 Stream URL Structure & M3U Format

### 1. Direct Stream URL Syntax
Every file inside an inspected remote archive receives a unique stream ID and endpoint:

```
http://<host>:<port>/stream/<entry_id>/<url_encoded_filename>
```

#### Examples:
- **Local Host:** `http://127.0.0.1:8787/stream/1/Episode_01_4K.mkv`
- **LAN Host (Living Room TV):** `http://192.168.1.100:8787/stream/3/Season01_Ep03.mp4`

---

### 2. M3U / M3U8 Playlist Syntax
ZipStreamHub generates standard extended M3U (`#EXTM3U`) playlists containing all video and audio entries discovered in the remote archive.

#### Sample `zipstream_playlist.m3u`:
```m3u
#EXTM3U
#EXTINF:-1 tvg-id="ep1" tvg-name="Episode 01" group-title="Season 1",Episode 01 - Pilot.mkv
http://127.0.0.1:8787/stream/1/Episode%2001%20-%20Pilot.mkv

#EXTINF:-1 tvg-id="ep2" tvg-name="Episode 02" group-title="Season 1",Episode 02 - The Journey.mkv
http://127.0.0.1:8787/stream/2/Episode%2002%20-%20The%20Journey.mkv

#EXTINF:-1 tvg-id="ep3" tvg-name="Episode 03" group-title="Season 1",Episode 03 - Discovery.mkv
http://127.0.0.1:8787/stream/3/Episode%2003%20-%20Discovery.mkv
```

#### Using M3U Playlists:
- Save the text file with a `.m3u` or `.m3u8` extension.
- Drag & drop the `.m3u` file directly into any player window.
- Or host/serve the playlist URL directly to IPTV apps and smart TVs.

---

## ⚡ Daum PotPlayer (Windows)

**PotPlayer** is the premier Windows media player with built-in hardware decoding, seamless playlist navigation, and 0-latency HTTP range seeking.

```
┌─────────────────────────────────────────────────────────────┐
│ [ZipStreamHub Web GUI] ──► Click "Play in PotPlayer"        │
│                           ▼                                 │
│ [PotPlayer] ──► Instant 4K HDR Playback (<0.6s)             │
└─────────────────────────────────────────────────────────────┘
```

### Method A: 1-Click Launch (Web GUI / CLI)
- In the Web GUI (`http://127.0.0.1:8787`), click **"▶ Play in PotPlayer"** next to any episode.
- From the CLI:
  ```powershell
  python cli.py "https://example.com/anime.zip" --ep 1 --player potplayer
  ```

### Method B: Manual URL Entry
1. Press `Ctrl + U` in PotPlayer (or right-click $\to$ **Open** $\to$ **Open URL...**).
2. Paste the stream URL (e.g. `http://127.0.0.1:8787/stream/1/Episode01.mkv`).
3. Click **OK**.

### Method C: Load M3U Playlist
- Press `F6` to open the PotPlayer Playlist drawer.
- Drag & drop `playlist.m3u` into the drawer.
- PotPlayer will list all episodes with track metadata.

### Recommended PotPlayer Settings:
- **Playback Buffer:** `Preferences (F5)` $\to$ `Playback` $\to$ set buffer to **3000ms**.
- **Hardware Acceleration:** `Filter Control` $\to$ `Video Decoder` $\to$ `Built-in OpenCodec/DXVA Settings` $\to$ Enable **D3D11 / DXVA2 Copy-Back**.

---

## 🎬 VLC Media Player (Cross-Platform)

VLC works natively on Windows, macOS, Linux, Android, iOS, and Apple TV.

### Method A: Open Network Stream (GUI)
1. Open VLC and press `Ctrl + N` (Windows/Linux) or `Cmd + N` (macOS).
2. Enter the stream URL:
   ```
   http://127.0.0.1:8787/stream/1/Episode01.mkv
   ```
3. Click **Play** (or press Enter).

### Method B: Command Line (CLI)
```bash
# Windows
& "C:\Program Files\VideoLAN\VLC\vlc.exe" "http://127.0.0.1:8787/stream/1/Episode01.mkv" --network-caching=3000

# macOS
/Applications/VLC.app/Contents/MacOS/VLC "http://127.0.0.1:8787/stream/1/Episode01.mkv" --network-caching=3000

# Linux
vlc "http://127.0.0.1:8787/stream/1/Episode01.mkv" --network-caching=3000
```

### Method C: Loading M3U Playlist in VLC
1. Open VLC $\to$ **Media** $\to$ **Open File...** (`Ctrl + O`).
2. Select your exported `playlist.m3u`.
3. Press `Ctrl + L` to toggle the Playlist view and double-click any episode.

---

## ▶️ MPV Player (Windows / macOS / Linux)

**MPV** is a lightweight, ultra-fast minimalist video player with superior audio/video sync and programmable shaders.

### Method A: Direct CLI Launch
```bash
# Direct stream launch with 64MB demuxer cache
mpv "http://127.0.0.1:8787/stream/1/Episode01.mkv" --cache=yes --demuxer-max-bytes=67108864
```

### Method B: Streaming M3U Playlist
```bash
mpv "path/to/playlist.m3u" --playlist-start=0
```

### Method C: Optimized `mpv.conf` Profile
Add these lines to your `mpv.conf` (`%APPDATA%\mpv\mpv.conf` on Windows or `~/.config/mpv/mpv.conf` on Linux/macOS):

```ini
# Network stream caching
cache=yes
demuxer-max-bytes=64MiB
demuxer-readahead-secs=20
demuxer-max-back-bytes=32MiB

# Hardware decoding
hwdec=auto-safe
vo=gpu-next
gpu-api=auto
```

---

## 📽️ MPC-HC & MPC-BE (Windows)

**Media Player Classic - Home Cinema / Black Edition** (included in K-Lite Codec Pack) is lightweight and supports high-bitrate HEVC/AV1 streams.

### Method A: Open File / URL
1. Open MPC-HC $\to$ Press `Ctrl + O` (or **File** $\to$ **Open File / URL...**).
2. Paste the stream URL into the **Open:** input box.
3. Click **OK**.

### Method B: Loading M3U Playlist
1. Press `Ctrl + 7` (or **View** $\to$ **Playlist**) to open the Playlist panel.
2. Drag & drop `playlist.m3u` into the list.
3. Double-click any episode to play.

---

## 📺 Kodi (Home Theater / Android TV / Fire TV)

**Kodi** is ideal for living room setups, Android TV boxes, NVIDIA Shield, and Fire TV sticks.

### Method A: Add Network Location (HTTP Direct)
1. Open Kodi $\to$ **Settings** (Gear icon) $\to$ **Media** $\to$ **Library** $\to$ **Videos...**
2. Select **Add videos...** $\to$ **Browse** $\to$ **Add network location...**
3. Configure:
   - **Protocol:** `Web server directory (HTTP)`
   - **Server address:** `192.168.1.100` (IP of machine running ZipStreamHub)
   - **Port:** `8787`
   - **Remote path:** `stream/`
4. Click **OK** to browse remote stream indices.

### Method B: Kodi IPTV Simple Client (M3U Integration)
1. In Kodi, go to **Add-ons** $\to$ **Install from repository** $\to$ **PVR clients** $\to$ **IPTV Simple Client**.
2. Open IPTV Simple Client settings $\to$ **Location:** `Local Path` or `Remote Path`.
3. Provide the path to `zipstream_playlist.m3u` (or the HTTP URL).
4. Restart Kodi $\to$ Navigate to **TV / Channels** to watch all episodes with EPG / channel metadata.

---

## 🍏 Infuse (Apple TV / iOS / iPadOS / macOS)

**Infuse** is the gold standard for Apple ecosystem playback, featuring full Dolby Vision Profile 5/7/8, Dolby Atmos, and automatic metadata fetching.

```
┌─────────────────────────────────────────────────────────────┐
│ [ZipStreamHub Server (PC/Mac)] ── (LAN/Wi-Fi)              │
│                           ▼                                 │
│ [Apple TV 4K / iPad / iPhone (Infuse Pro)]                  │
│  - 4K Dolby Vision & Atmos direct stream                    │
│  - Instant random seeking                                   │
└─────────────────────────────────────────────────────────────┘
```

### Method A: Add Direct Stream URL
1. Open Infuse on iPhone, iPad, Mac, or Apple TV.
2. Go to **Settings** $\to$ **Shares** $\to$ **Add** $\to$ **Direct URL**.
3. Enter the URL:
   ```
   http://192.168.1.100:8787/stream/1/Movie.4K.mkv
   ```
4. Click **Save** and start watching immediately.

### Method B: M3U Playlist in Infuse
1. Open the Files app on iOS / macOS.
2. Share or air-drop `playlist.m3u` to Infuse.
3. Infuse will import all episode links into your home screen library with full cover art and chapter support.

---

## 🖥️ IINA (macOS)

**IINA** is the modern media player designed specifically for macOS with Apple Silicon (M1/M2/M3/M4) hardware decoding and Touch Bar support.

### Method A: 1-Click Launch from Terminal / CLI
```bash
open -a IINA "http://127.0.0.1:8787/stream/1/Episode01.mkv"
# or if 'iina' CLI tool is installed:
iina "http://127.0.0.1:8787/stream/1/Episode01.mkv"
```

### Method B: Open URL in IINA
1. Launch IINA $\to$ Press `Cmd + Shift + O` (or **File** $\to$ **Open URL...**).
2. Enter the stream URL.
3. Click **Open**.

### Method C: Load M3U Playlist
- Drag `playlist.m3u` onto the IINA window or dock icon.
- Press `Cmd + P` to toggle the playlist sidebar.

---

## 💬 Subtitles & WebVTT Auto-Conversion

ZipStreamHub features an automated subtitle discovery and streaming pipeline:

### 1. Embedded Subtitles (MKV / MP4)
- Native players (**PotPlayer**, **VLC**, **MPV**, **IINA**, **Infuse**) demux embedded subtitle tracks (`ASS`, `SRT`, `PGS`, `VobSub`) on-the-fly directly through the HTTP 206 byte-range stream.
- No extraction required.

### 2. External Subtitles in ZIP Archive
- When the remote ZIP contains paired subtitle files (e.g. `Episode01.srt` alongside `Episode01.mkv`), ZipStreamHub detects matching base names.
- For Web Player clients, `.srt` streams are converted on-the-fly to standard **WebVTT (`text/vtt`)** tracks via `/stream/<sub_id>/sub.vtt`.

---

## 📡 LAN & Remote Network Streaming

To stream from ZipStreamHub to other devices in your home network (e.g. Smart TV, Phone, Apple TV):

### 1. Bind to All Network Interfaces
Set `host` to `"0.0.0.0"` in `config.json`:
```json
{
  "server": {
    "host": "0.0.0.0",
    "port": 8787
  }
}
```

### 2. Find Your Host LAN IP Address
- **Windows:** Run `ipconfig` in PowerShell (e.g. `192.168.1.100`).
- **macOS / Linux:** Run `ifconfig` or `ip a` (e.g. `192.168.1.100`).

### 3. Allow Firewall Access
- **Windows:** Allow port `8787` in Windows Defender Firewall:
  ```powershell
  New-NetFirewallRule -DisplayName "ZipStreamHub" -Direction Inbound -LocalPort 8787 -Protocol TCP -Action Allow
  ```

### 4. Open Streams on Any Client Device
On your phone, tablet, or smart TV player, replace `127.0.0.1` with `192.168.1.100`:
```
http://192.168.1.100:8787/stream/1/Episode01.mkv
```
