import http.server
import socketserver
import socket
import json
import ssl
import sys
import os
import mimetypes
import subprocess
import threading
from typing import Dict, Optional, Tuple
from zip_stream_engine import RemoteZipReader, StreamPrefetcher, HTTP_POOL

PORT = 8787

# Multi-Archive Cache & Concurrency Lock
ARCHIVE_LOCK = threading.Lock()
CURRENT_READER: Optional[RemoteZipReader] = None
CACHED_ENTRIES: Dict[int, dict] = {}
READERS_BY_URL: Dict[str, RemoteZipReader] = {}


class ThreadedZipStreamServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """
    High-concurrency multi-threaded HTTP server.
    - daemon_threads = True: Worker threads terminate immediately when parent closes.
    - TCP_NODELAY: Disables Nagle algorithm for 0-latency player seek and packet response.
    - SO_KEEPALIVE: Keeps connection alive for rapid player probing.
    """
    daemon_threads = True
    allow_reuse_address = True

    def server_bind(self):
        super().server_bind()
        try:
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        except Exception:
            pass

    def finish_request(self, request, client_address):
        try:
            request.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except Exception:
            pass
        super().finish_request(request, client_address)


class ZipStreamWebHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _set_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Range, Content-Type, Accept, Origin, User-Agent")
        self.send_header("Access-Control-Expose-Headers", "Content-Range, Content-Length, Accept-Ranges")

    def do_OPTIONS(self):
        self.send_response(204)
        self._set_cors_headers()
        self.send_header("Content-Length", "0")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

    def do_HEAD(self):
        if self.path.startswith("/stream/"):
            self._handle_stream_head()
        elif self.path in ("/", "/index.html"):
            self.send_response(200)
            self._set_cors_headers()
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
        else:
            self.send_response(200)
            self._set_cors_headers()
            self.send_header("Connection", "keep-alive")
            self.end_headers()

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._serve_file("E:/ZipStreamHub/web_gui.html", "text/html")
        elif self.path.startswith("/stream/"):
            self._handle_stream_get()
        else:
            self.send_response(404)
            self._set_cors_headers()
            self.end_headers()

    def do_POST(self):
        if self.path == "/api/inspect":
            self._handle_api_inspect()
        elif self.path == "/api/play":
            self._handle_api_play()
        else:
            self.send_response(404)
            self._set_cors_headers()
            self.end_headers()

    def _serve_file(self, filepath: str, content_type: str):
        try:
            with open(filepath, "rb") as f:
                content = f.read()
            self.send_response(200)
            self._set_cors_headers()
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_response(500)
            self._set_cors_headers()
            self.end_headers()
            self.wfile.write(str(e).encode())

    def _handle_api_inspect(self):
        global CURRENT_READER, CACHED_ENTRIES, READERS_BY_URL
        length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(length)
        try:
            body = json.loads(post_data.decode("utf-8"))
            zip_url = body.get("url", "").strip()
            if not zip_url:
                raise ValueError("Missing url field")

            with ARCHIVE_LOCK:
                if zip_url in READERS_BY_URL:
                    reader = READERS_BY_URL[zip_url]
                else:
                    reader = RemoteZipReader(zip_url)
                    READERS_BY_URL[zip_url] = reader

                CURRENT_READER = reader
                CACHED_ENTRIES = {e["id"]: e for e in reader.entries}

            resp = {
                "status": "ok",
                "total_size_gb": round(reader.total_size / (1024 ** 3), 2),
                "total_size_bytes": reader.total_size,
                "entries": reader.entries
            }
            data_bytes = json.dumps(resp).encode("utf-8")
            self.send_response(200)
            self._set_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data_bytes)))
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            self.wfile.write(data_bytes)
        except Exception as e:
            err_bytes = json.dumps({"status": "error", "error": str(e)}).encode("utf-8")
            self.send_response(500)
            self._set_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(err_bytes)))
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            self.wfile.write(err_bytes)

    def _handle_api_play(self):
        length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(length)
        try:
            body = json.loads(post_data.decode("utf-8"))
            stream_url = body.get("url")

            potplayer_paths = [
                r"C:\Program Files\DAUM\PotPlayer\PotPlayerMini64.exe",
                r"C:\Program Files (x86)\DAUM\PotPlayer\PotPlayerMini.exe",
                r"C:\Program Files\DAUM\PotPlayer\PotPlayer64.exe",
                r"C:\Program Files\VideoLAN\VLC\vlc.exe",
                r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe"
            ]
            player_exe = next((p for p in potplayer_paths if os.path.exists(p)), None)

            if player_exe:
                subprocess.Popen([player_exe, stream_url])
                resp = json.dumps({"status": "ok", "message": f"Launched player: {os.path.basename(player_exe)}"}).encode("utf-8")
            else:
                resp = json.dumps({"status": "error", "message": "Supported player executable not found"}).encode("utf-8")

            self.send_response(200)
            self._set_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp)))
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            self.wfile.write(resp)
        except Exception as e:
            resp = json.dumps({"status": "error", "error": str(e)}).encode("utf-8")
            self.send_response(500)
            self._set_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp)))
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            self.wfile.write(resp)

    def _get_target_entry_and_offset(self) -> Tuple[Optional[dict], Optional[int], Optional[RemoteZipReader]]:
        # Format: /stream/<id>/<filename>
        parts = self.path.split("/")
        if len(parts) < 3:
            return None, None, None
        try:
            ep_id = int(parts[2])
            with ARCHIVE_LOCK:
                entry = CACHED_ENTRIES.get(ep_id)
                reader = CURRENT_READER
            if not entry or not reader:
                return None, None, None

            data_start = reader.get_data_offset(entry)
            return entry, data_start, reader
        except Exception:
            return None, None, None

    def _get_mime_type(self, filename: str) -> str:
        lower = filename.lower()
        if lower.endswith(".mkv"):
            return "video/x-matroska"
        elif lower.endswith(".mp4"):
            return "video/mp4"
        elif lower.endswith(".webm"):
            return "video/webm"
        elif lower.endswith(".avi"):
            return "video/x-msvideo"
        elif lower.endswith(".ts"):
            return "video/mp2t"
        elif lower.endswith(".mov"):
            return "video/quicktime"
        elif lower.endswith(".mp3"):
            return "audio/mpeg"
        elif lower.endswith(".m4a"):
            return "audio/mp4"
        elif lower.endswith(".flac"):
            return "audio/flac"
        mime, _ = mimetypes.guess_type(filename)
        return mime or "application/octet-stream"

    def _handle_stream_head(self):
        entry, _, _ = self._get_target_entry_and_offset()
        if not entry:
            self.send_response(404)
            self._set_cors_headers()
            self.end_headers()
            return

        total_file_size = entry["size_bytes"]
        mime_type = self._get_mime_type(entry["name"])

        self.send_response(200)
        self._set_cors_headers()
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Type", mime_type)
        self.send_header("Content-Length", str(total_file_size))
        self.send_header("Connection", "keep-alive")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

    def _handle_stream_get(self):
        entry, data_start, reader = self._get_target_entry_and_offset()
        if not entry or data_start is None or not reader:
            self.send_response(404)
            self._set_cors_headers()
            self.end_headers()
            return

        total_file_size = entry["size_bytes"]
        mime_type = self._get_mime_type(entry["name"])
        range_header = self.headers.get("Range")

        if not range_header:
            start_byte = 0
            end_byte = total_file_size - 1
            status_code = 200
        else:
            try:
                range_val = range_header.strip().replace("bytes=", "")
                if range_val.startswith("-"):
                    suffix = int(range_val[1:])
                    start_byte = max(0, total_file_size - suffix)
                    end_byte = total_file_size - 1
                elif "-" in range_val:
                    parts = range_val.split("-")
                    start_byte = int(parts[0])
                    end_byte = int(parts[1]) if parts[1] else total_file_size - 1
                else:
                    start_byte = int(range_val)
                    end_byte = total_file_size - 1

                # Bounds checking
                if start_byte >= total_file_size or start_byte > end_byte:
                    self.send_response(416)
                    self._set_cors_headers()
                    self.send_header("Content-Range", f"bytes */{total_file_size}")
                    self.end_headers()
                    return

                end_byte = min(end_byte, total_file_size - 1)
                status_code = 206
            except Exception:
                start_byte = 0
                end_byte = total_file_size - 1
                status_code = 200

        content_length = end_byte - start_byte + 1
        remote_start = data_start + start_byte
        remote_end = data_start + end_byte

        self.send_response(status_code)
        self._set_cors_headers()
        self.send_header("Content-Type", mime_type)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(content_length))
        if status_code == 206:
            self.send_header("Content-Range", f"bytes {start_byte}-{end_byte}/{total_file_size}")
        self.send_header("Connection", "keep-alive")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        # High-Throughput Read-Ahead Prefetch Buffer
        prefetcher = StreamPrefetcher(
            url=reader.url,
            start_byte=remote_start,
            end_byte=remote_end,
            pool=HTTP_POOL
        )
        prefetcher.start()

        try:
            for chunk in prefetcher.stream_chunks():
                self.wfile.write(chunk)
                self.wfile.flush()
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
            self.close_connection = True
        except Exception:
            self.close_connection = True
        finally:
            prefetcher.close()

    def log_message(self, format, *args):
        if "/stream/" not in self.path:
            sys.stdout.write(f"[HTTP] {format % args}\n")
            sys.stdout.flush()


def run_server():
    server_address = ("127.0.0.1", PORT)
    httpd = ThreadedZipStreamServer(server_address, ZipStreamWebHandler)
    print(f"ZipStream Hub (High-Performance Engine) running on http://127.0.0.1:{PORT}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down ZipStream Hub...")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    run_server()
