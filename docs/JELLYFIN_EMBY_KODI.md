# 🍿 Jellyfin, Emby & Kodi: Virtual Library Mounting via STRM Bundles

**ZipStreamHub** enables direct playback of multi-gigabyte or multi-terabyte cloud ZIP archives (100GB+) in **Jellyfin**, **Emby**, and **Kodi** with **0 bytes of video downloaded or stored on local disk**.

By generating lightweight `.strm` (Stream Pointer) files organized in standard media server naming hierarchies, your media server indexes, scrapes metadata, downloads poster artwork, and streams cloud media files on demand via HTTP 206 byte-range seeking.

---

## 📑 Table of Contents
1. [What is an STRM Virtual Bundle?](#-what-is-an-strm-virtual-bundle)
2. [How Zero-Disk Cloud Streaming Works](#-how-zero-disk-cloud-streaming-works)
3. [Exporting STRM Bundles from ZipStreamHub](#-exporting-strm-bundles-from-zipstreamhub)
   - [Method A: REST API (`/api/strm.zip`)](#method-a-rest-api-apistrmzip)
   - [Method B: Interactive CLI](#method-b-interactive-cli)
4. [Jellyfin Setup & Library Integration](#-jellyfin-setup--library-integration)
5. [Emby Setup & Library Integration](#-emby-setup--library-integration)
6. [Kodi Setup & Direct Library Integration](#-kodi-setup--direct-library-integration)
7. [Directory Structure & Auto-Naming Rules](#-directory-structure--auto-naming-rules)
8. [Performance Tuning & Direct Play Optimization](#-performance-tuning--direct-play-optimization)
9. [Troubleshooting Common Issues](#-troubleshooting-common-issues)

---

## 💡 What is an STRM Virtual Bundle?

An `.strm` file is a plain text file containing a single direct stream URL. 

When a media server (Jellyfin/Emby/Kodi) encounters a `.strm` file in its media library folders:
1. It treats the file like a native video (`.mkv`, `.mp4`).
2. Scrapers identify the title and fetch metadata, cast info, chapter markers, and poster artwork.
3. When playback starts, the media server streams the video directly from the ZipStreamHub HTTP endpoint without transcoding or pre-downloading.

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Local Disk (0 Bytes Video)                     │
│  E:\Media\TV Shows\Severance\Season 01\Severance S01E01.strm (48 bytes)│
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │ Points to: http://127.0.0.1:8787/stream/1/Ep1.mkv
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        ZipStreamHub Engine                             │
│       Translates HTTP Range 206 Requests to Cloud Archive Byte Offsets │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │ Direct HTTP Byte-Range Stream
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   Remote Cloud Storage / ZIP File (100GB+)             │
└────────────────────────────────────────────────────────────────────────┘
```

---

## ⚡ How Zero-Disk Cloud Streaming Works

1. **Central Directory Discovery:** ZipStreamHub reads only the tail (~1MB) of the remote 100GB+ ZIP archive to index all video files and their byte offsets in ~0.6 seconds.
2. **Virtual STRM Generation:** ZipStreamHub creates an in-memory ZIP package containing tiny `.strm` files (each < 100 bytes) mapped to the server's streaming endpoints.
3. **Transparent Seeking:** As you seek through 4K HDR REMUX or 1080p video in Jellyfin/Emby/Kodi, the media player sends standard HTTP `Range: bytes=start-end` headers, which ZipStreamHub converts to exact byte offsets inside the remote ZIP.

---

## 📦 Exporting STRM Bundles from ZipStreamHub

### Method A: REST API (`/api/strm.zip`)

Download a complete, organized ZIP bundle containing all `.strm` pointer files for any remote archive:

```bash
# Export using the active loaded archive:
curl -O -J "http://127.0.0.1:8787/api/strm.zip"

# Export for a specific remote ZIP URL with standard auto-naming:
curl -O -J "http://127.0.0.1:8787/api/strm.zip?url=https://storage.googleapis.com/demo/Season01.zip&structure=auto"

# Export flat or mirroring directory structure:
curl -O -J "http://127.0.0.1:8787/api/strm.zip?url=https://storage.googleapis.com/demo/Movies.zip&structure=flat"
```

#### Query Parameters:
| Parameter | Type | Default | Description |
|---|---|---|---|
| `url` | `string` | *(active archive)* | Fully qualified URL of remote ZIP archive |
| `structure` | `string` | `auto` | Directory layout: `auto` (Show/Season hierarchy), `flat` (all files in root), or `mirror` (replicate archive paths) |

---

### Method B: Interactive CLI

Export `.strm` bundles directly via `cli.py`:

```bash
# Non-interactive export to a specified ZIP file
python cli.py "https://example.com/Season01.zip" --export-strm "E:\Media\Jellyfin_TV.zip"

# Inside interactive CLI shell:
python cli.py "https://example.com/Season01.zip"
# Type command:
> strm season1_strm.zip
```

---

## 🍇 Jellyfin Setup & Library Integration

Jellyfin has native support for `.strm` files and handles direct streaming smoothly.

### Step-by-Step Instructions:

1. **Extract STRM Bundle to Media Folder:**
   Extract the generated `strm_bundle.zip` into your Jellyfin media storage directory (e.g., `E:\Media\Shows` or `/media/shows`).
   ```
   E:\Media\Shows\
   └── Succession\
       └── Season 04\
           ├── Succession S04E01.strm
           ├── Succession S04E02.strm
           └── Succession S04E03.strm
   ```

2. **Add Folder in Jellyfin Dashboard:**
   - Open Jellyfin Web Dashboard (`http://localhost:8096`).
   - Navigate to **Administration** $\to$ **Dashboard** $\to$ **Libraries**.
   - Click **+ Add Media Library**.
   - **Content type:** Select `Shows` (for series) or `Movies`.
   - **Display name:** e.g., `Cloud Shows (ZipStream)`.
   - **Folders:** Add `E:\Media\Shows` (or the corresponding container path).

3. **Configure Library Settings:**
   - **Preferred download language:** English / Your choice.
   - **Metadata downloaders:** Check *TheMovieDb* and *TheTVDB*.
   - **Automatically refresh metadata from the internet:** Enabled.
   - Click **OK**.

4. **Scan Library Files:**
   - Click the three dots on your new library and select **Scan Library**.
   - Jellyfin reads the `.strm` filenames, queries TMDB/TVDB, downloads posters and episode summaries, and generates thumbnails.

5. **Start Playback:**
   - Click any episode in the Jellyfin web app, Android TV, Apple TV, or mobile app.
   - Jellyfin immediately requests the stream from `http://127.0.0.1:8787/stream/...`.

---

## 🟢 Emby Setup & Library Integration

Emby provides out-of-the-box support for `.strm` stream files with direct play capability.

### Step-by-Step Instructions:

1. **Extract STRM Files to Target Folder:**
   Extract the virtual `.strm` archive into your Emby media directory (e.g., `E:\EmbyMedia\Movies` or `E:\EmbyMedia\TV`).

2. **Add Media Library in Emby:**
   - Open Emby Server Manager (`http://localhost:8096`).
   - Go to **Settings** $\to$ **Server** $\to$ **Library**.
   - Click **+ New Library**.
   - Choose `TV Shows` or `Movies`.
   - Add the folder path where your `.strm` files reside.

3. **Verify Playback & Transcoding Policy:**
   - Under **Users** $\to$ Select User $\to$ **Media Playback**:
   - Ensure **Allow video playback that requires transcoding** and **Allow audio playback that requires transcoding** are checked (or set to Direct Play preference).
   - Emby will attempt Direct Stream / Direct Play first.

4. **Trigger Scan & Watch:**
   - Click **Scan Library files**.
   - Browse your library and enjoy zero-download streaming.

---

## 📺 Kodi Setup & Direct Library Integration

Kodi has native support for `.strm` files and handles high-bitrate streaming without any transcoding.

### Option 1: File Source (Quick & Direct)

1. Open Kodi $\to$ Go to **Settings (Gear Icon)** $\to$ **Media** $\to$ **Library** $\to$ **Videos...**
2. Select **Add videos...** $\to$ Click **Browse**.
3. Browse to the local directory where you extracted the `.strm` files (e.g., `E:\Media\Shows\`).
4. Set content type:
   - **This directory contains:** `TV shows` or `Movies`.
   - **Choose information provider:** `TMDb TV Shows` / `The Movie Database Python`.
5. Click **OK** and allow Kodi to scan the library.

### Option 2: Live M3U Playlist Integration

If you prefer not to extract `.strm` files:
1. Enable the **IPTV Simple Client** add-on in Kodi.
2. Set the M3U Playlist URL to: `http://127.0.0.1:8787/api/playlist.m3u`
3. All episodes in the currently inspected archive will appear immediately under Kodi TV / Channels.

---

## 📂 Directory Structure & Auto-Naming Rules

ZipStreamHub's `strm_generator` parses scene release titles, episode codes, and directory hierarchies to format files for 100% scraper accuracy:

| Archive Filename Pattern | Auto-Generated STRM Path | Scraper Compatibility |
|---|---|---|
| `Severance.S01E01.1080p.mkv` | `Severance/Season 01/Severance S01E01.strm` | Jellyfin, Emby, Kodi, Plex |
| `Game.of.Thrones.S08E06.2160p.mkv` | `Game of Thrones/Season 08/Game of Thrones S08E06.strm` | Jellyfin, Emby, Kodi |
| `Interstellar.2014.1080p.mkv` | `Interstellar (2014)/Interstellar (2014).strm` | Jellyfin, Emby, Kodi |
| `Shows/Breaking Bad/Season 1/01.mkv` | `Breaking Bad/Season 01/Breaking Bad S01E01.strm` | Jellyfin, Emby, Kodi |

---

## ⚡ Performance Tuning & Direct Play Optimization

To guarantee maximum streaming throughput and eliminate stutter during 4K HDR playback:

1. **Keep ZipStreamHub Running on Same LAN / Host:**
   If Jellyfin is hosted on a different machine on your local network, specify the host IP when creating STRM links:
   ```bash
   # When generating bundles for a remote LAN server:
   # Pass Host header or configure ZIPSTREAM_HOST=0.0.0.0
   ```
2. **Enable Direct Play (Disable Transcoding):**
   In Jellyfin/Emby user profiles, enable **Direct Play** for container formats (`MKV`, `MP4`) so the server passes the HTTP 206 stream directly to the client player without CPU-heavy re-encoding.
3. **Increase Prefetch Buffer:**
   For multi-gigabyte 4K REMUX files, configure `ZIPSTREAM_PREFETCH_MB=1024` or `2048` in `.env` to ensure continuous buffer headroom during network fluctuations.

---

## 🔧 Troubleshooting Common Issues

### 1. Jellyfin / Emby Shows "Play method: Transcode"
- **Cause:** Client device does not support the audio codec (e.g., TrueHD/DTS-HD MA) or video profile (e.g., AV1/10-bit HEVC).
- **Fix:** Jellyfin will transcode audio on the fly while streaming the video from ZipStreamHub. For 100% Direct Play, use client players like Kodi, Infuse, or MPV.

### 2. Metadata Scraper Fails to Match
- **Cause:** Archive contains non-standard names without year or season numbers.
- **Fix:** In Jellyfin/Emby, right-click the item $\to$ select **Identify** $\to$ enter the TMDB / IMDB ID (e.g., `tt11280740`).

### 3. Server Returns 404 on Stream Request
- **Cause:** ZipStreamHub server was restarted with a different archive, or the archive index was cleared.
- **Fix:** Inspect the ZIP archive again via Web GUI or `/api/inspect` to load the Central Directory into cache.
