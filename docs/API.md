# 🔌 ZipStreamHub REST API Reference

The ZipStreamHub REST API provides programmatic control over remote ZIP/ZIP64 archive parsing, stream generation, and media player execution.

Base URL: `http://localhost:8787` (Default)  
Protocol: `HTTP/1.1`  
CORS: Enabled for all origins (`Access-Control-Allow-Origin: *`)

---

## 📑 Endpoints Overview

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/inspect` | Parses remote ZIP/ZIP64 and returns file metadata |
| `POST` | `/api/play` | Launches host-installed media player for a stream |
| `GET` | `/stream/<id>/<filename>` | Stream video/audio file with HTTP 206 Range support |
| `HEAD` | `/stream/<id>/<filename>` | Probe stream headers, content length, and MIME type |
| `OPTIONS` | `/*` | CORS preflight handler |
| `GET` | `/` | Web GUI Dashboard HTML interface |

---

## 1. Inspect Remote Archive

### `POST /api/inspect`
Analyzes a remote ZIP or ZIP64 URL by fetching only the archive's tail and Central Directory headers.

#### Request Body
- **Content-Type**: `application/json`

```json
{
  "url": "https://example.com/movies/Season01.zip"
}
```

| Parameter | Type | Required | Description |
|---|---|---|---|
| `url` | `string` | **Yes** | Fully qualified HTTP/HTTPS direct link to remote ZIP/ZIP64 file |

#### Response (`200 OK`)
```json
{
  "status": "ok",
  "total_size_gb": 48.35,
  "total_size_bytes": 51915472896,
  "entries": [
    {
      "id": 1,
      "name": "Episode01_4K.mkv",
      "full_path": "Season01/Episode01_4K.mkv",
      "method": 0,
      "method_name": "STORE",
      "size_bytes": 4294967296,
      "comp_size_bytes": 4294967296,
      "size_gb": 4.0,
      "size_mb": 4096.0,
      "local_header_offset": 128,
      "data_offset": 224
    },
    {
      "id": 2,
      "name": "Episode02_4K.mkv",
      "full_path": "Season01/Episode02_4K.mkv",
      "method": 0,
      "method_name": "STORE",
      "size_bytes": 4510023680,
      "comp_size_bytes": 4510023680,
      "size_gb": 4.2,
      "size_mb": 4301.1,
      "local_header_offset": 4294967424,
      "data_offset": 4294967520
    }
  ]
}
```

#### Error Responses
- **`500 Internal Server Error`**:
```json
{
  "status": "error",
  "error": "Could not determine archive total size or server does not support Range requests."
}
```

---

## 2. Launch Local Media Player

### `POST /api/play`
Commands the server to launch a supported desktop media player (PotPlayer, VLC, MPV) with the provided stream URL.

#### Request Body
- **Content-Type**: `application/json`

```json
{
  "url": "http://127.0.0.1:8787/stream/1/Episode01_4K.mkv"
}
```

| Parameter | Type | Required | Description |
|---|---|---|---|
| `url` | `string` | **Yes** | Local ZipStreamHub `/stream/...` URL to play |

#### Response (`200 OK`)
```json
{
  "status": "ok",
  "message": "Launched player: PotPlayerMini64.exe"
}
```

```json
{
  "status": "error",
  "message": "Supported player executable not found"
}
```

---

## 3. Media Stream Endpoint

### `GET /stream/<id>/<filename>`
High-throughput, seekable media streaming endpoint. Directly interfaces with media player demuxers and browser `<video>` elements.

#### Path Parameters
| Parameter | Type | Description |
|---|---|---|
| `id` | `integer` | Entry ID obtained from `/api/inspect` |
| `filename` | `string` | File name for player presentation and MIME resolution |

#### Request Headers
| Header | Value | Description |
|---|---|---|
| `Range` | `bytes=0-1048575` *(optional)* | HTTP 1.1 Byte-range request for partial content |
| `User-Agent` | `Lavf/60.16.100` *(optional)* | Player client user agent |

#### Response Headers (`206 Partial Content`)
```http
HTTP/1.1 206 Partial Content
Content-Type: video/x-matroska
Accept-Ranges: bytes
Content-Length: 1048576
Content-Range: bytes 0-1048575/4294967296
Connection: keep-alive
Cache-Control: no-cache
Access-Control-Allow-Origin: *
Access-Control-Expose-Headers: Content-Range, Content-Length, Accept-Ranges
```

#### Stream MIME Type Mapping
| Extension | Content-Type Header |
|---|---|
| `.mkv` | `video/x-matroska` |
| `.mp4` | `video/mp4` |
| `.webm` | `video/webm` |
| `.avi` | `video/x-msvideo` |
| `.ts` | `video/mp2t` |
| `.mov` | `video/quicktime` |
| `.mp3` | `audio/mpeg` |
| `.m4a` | `audio/mp4` |
| `.flac` | `audio/flac` |

---

## 4. Stream Header Probe

### `HEAD /stream/<id>/<filename>`
Used by media players (like FFmpeg, PotPlayer, VLC) to discover file size and verify byte-range seeking capability without downloading any content.

#### Response Headers (`200 OK`)
```http
HTTP/1.1 200 OK
Accept-Ranges: bytes
Content-Type: video/x-matroska
Content-Length: 4294967296
Connection: keep-alive
Cache-Control: no-cache
Access-Control-Allow-Origin: *
```

---

## 5. cURL Integration Examples

### Inspect Archive:
```bash
curl -X POST http://127.0.0.1:8787/api/inspect \
  -H "Content-Type: application/json" \
  -d '{"url": "https://storage.googleapis.com/demo/sample_videos.zip"}'
```

### Probe Stream Range:
```bash
curl -I http://127.0.0.1:8787/stream/1/Sample.mkv \
  -H "Range: bytes=0-1048575"
```

### Stream First 10MB to File:
```bash
curl -r 0-10485759 http://127.0.0.1:8787/stream/1/Sample.mkv -o first_10mb.mkv
```
