# 🛠️ ZipStreamHub Troubleshooting & Optimization Guide

This guide covers common issues, server rate limits, network timeouts, codec compatibility, and optimal media player settings.

---

## 1. Common Issues & Quick Solutions

### Issue: "Valid ZIP End of Central Directory record not found"
- **Cause**: 
  1. The URL provided is not a direct file link (e.g., HTML landing page or Google Drive confirmation page).
  2. The remote server returned a 403 Forbidden or 404 Not Found error.
  3. The ZIP file is corrupted or truncated.
- **Solution**:
  - Test the URL in your browser: it must trigger an immediate binary download.
  - For Google Drive, use a direct download link generator.
  - For OneDrive / Dropbox, ensure `?download=1` is appended.

---

### Issue: "Server does not support Range requests"
- **Cause**: The remote hosting server or CDN does not support HTTP `Range: bytes=X-Y` requests (HTTP 206 status).
- **Solution**:
  - ZipStreamHub requires HTTP Range support for zero-download streaming.
  - If hosting on Nginx/Apache, ensure `Accept-Ranges: bytes` is enabled.
  - If using Cloudflare, verify range requests are not disabled in Cloudflare Page Rules / WAF.

---

### Issue: Playback Works but Seeking Stutters or Fails
- **Cause**: The ZIP file was created with `DEFLATE` compression instead of `STORE`.
- **Explanation**: 
  - `STORE (Method 0)`: Files are stored without compression. Byte offsets translate 1:1, allowing instantaneous seeking.
  - `DEFLATE (Method 8)`: Data is compressed into dynamic Huffman blocks. Seeking to an arbitrary byte requires decompressing all preceding blocks.
- **Solution**:
  - Re-pack the archive using `Store / Copy` compression:
    ```bash
    # 7-Zip Command Line (0% compression = instant streaming)
    7z a -mx0 output.zip "path/to/videos/*"
    ```

---

## 2. CDN & Cloudflare Rate Limiting (429 / 503)

When streaming high-bitrate 4K media, frequent 2MB range requests may trigger CDN rate limits.

### Workarounds:
1. **Connection Pooling**: ZipStreamHub automatically uses `urllib3.PoolManager` with persistent HTTP Keep-Alive connections to reduce TCP/TLS handshakes.
2. **Increase Prefetch Block Size**: In `engine.py`, adjust `BLOCK_SIZE` from `2MB` to `4MB` or `8MB` to reduce request frequency.
3. **Cloudflare Worker Rules**: If proxying through a Cloudflare Worker, ensure it passes through the `Range` and `Content-Range` headers without buffering entire responses.

---

## 3. Video Codec & Container Compatibility

| Container / Extension | Recommended Codec | Browser Playback | PotPlayer / MPV / VLC |
|---|---|---|---|
| `.mkv` (Matroska) | H.264 / H.265 / AV1 | Partial (Chrome/Edge with WebM) | **100% Native & Hardware Accelerated** |
| `.mp4` | H.264 + AAC | **100% Native** | **100% Native** |
| `.webm` | VP9 / AV1 + Opus | **100% Native** | **100% Native** |
| `.ts` | H.264 / MPEG-2 | Requires hls.js | **100% Native** |
| `.avi` | Xvid / DivX | No | **100% Native** |

> **Pro Tip**: For the best cross-platform experience, we recommend `.mkv` or `.mp4` containers encoded with **H.264/H.265** and **AAC/AC3/E-AC3** audio tracks.

---

## 4. Player-Specific Optimization Tips

### PotPlayer (Windows)
- **Direct Launch**: ZipStreamHub can launch PotPlayer automatically via the Web GUI or CLI.
- **Network Buffer**: 
  - Go to `Preferences (F5)` -> `Playback` -> set **Network Buffer** to `10 sec`.
  - Enable **Seamless Playback** for episode binge-watching.

### MPV (Cross-Platform)
- Launch with fast network buffering options:
  ```bash
  mpv --demuxer-max-bytes=150M --demuxer-readahead-secs=20 "http://127.0.0.1:8787/stream/1/Episode.mkv"
  ```

### VLC Media Player
- Enable fast HTTP caching:
  - Go to `Tools` -> `Preferences` -> `Show settings: All` -> `Input / Codecs` -> `Advanced`.
  - Set **Network caching (ms)** to `3000` (3 seconds).

---

## 5. Port Conflict (`8787` already in use)

If port 8787 is already occupied by another service:
1. Edit `config.json` and change `"port": 8787` to another port (e.g. `9090`).
2. Or run via CLI:
   ```bash
   python server.py --port 9090
   ```
