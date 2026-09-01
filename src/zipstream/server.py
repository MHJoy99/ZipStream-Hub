import http.server
import socketserver
import socket
import json
import ssl
import sys
import os
import time
import mimetypes
import subprocess
import threading
import urllib.parse
import urllib.request
import urllib.error
import argparse
from typing import Dict, Optional, Tuple, List

# Clean intra-package / local directory imports
try:
    from .engine import (
        RemoteZipReader,
        StreamPrefetcher,
        HTTP_POOL,
        METRICS,
        get_streaming_metrics,
        set_bandwidth_limit,
    )
    from .player_detector import get_installed_players, launch_stream
    from .subtitle_parser import is_video_file, is_subtitle_file, convert_to_vtt
    from .webdav_bridge import WebDAVBridge
    from .strm_generator import generate_strm_zip_bundle
    from .media_inspector import MediaInspector, inspect_media_header
    from . import history
    from .config import load_config, AppConfig
    from . import __version__
except ImportError:
    from engine import (
        RemoteZipReader,
        StreamPrefetcher,
        HTTP_POOL,
        METRICS,
        get_streaming_metrics,
        set_bandwidth_limit,
    )
    from player_detector import get_installed_players, launch_stream
    from subtitle_parser import is_video_file, is_subtitle_file, convert_to_vtt
    from webdav_bridge import WebDAVBridge
    from strm_generator import generate_strm_zip_bundle
    from media_inspector import MediaInspector, inspect_media_header
    import history
    from config import load_config, AppConfig
    try:
        from __init__ import __version__
    except ImportError:
        __version__ = "1.0.0"

PORT = 8787
ACTIVE_PORT_FILE = ".active_port"
SERVER_START_TIME = time.time()


def get_active_port(fallback: int = PORT) -> int:
    """Reads the active port from .active_port file if present, else fallback."""
    for base in [os.getcwd(), os.path.dirname(os.path.abspath(__file__)), os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]:
        path = os.path.join(base, ACTIVE_PORT_FILE)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    val = int(f.read().strip())
                    if 1 <= val <= 65535:
                        return val
            except Exception:
                pass
    return fallback


def save_active_port(port: int):
    """Saves the active port to .active_port in cwd and package directory."""
    bases = {os.getcwd(), os.path.dirname(os.path.abspath(__file__)), os.path.dirname(os.path.dirname(os.path.abspath(__file__)))}
    for base in bases:
        try:
            path = os.path.join(base, ACTIVE_PORT_FILE)
            with open(path, "w", encoding="utf-8") as f:
                f.write(str(port))
        except Exception:
            pass


def remove_active_port_file():
    """Removes .active_port file on clean shutdown."""
    bases = {os.getcwd(), os.path.dirname(os.path.abspath(__file__)), os.path.dirname(os.path.dirname(os.path.abspath(__file__)))}
    for base in bases:
        try:
            path = os.path.join(base, ACTIVE_PORT_FILE)
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass


def is_port_available(port: int, host: str = "127.0.0.1") -> bool:
    """Checks if a TCP port can be bound."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
            return True
        except OSError:
            return False


def find_free_port(start_port: int = PORT, max_attempts: int = 100, host: str = "127.0.0.1") -> int:
    """Hunts for the next available port starting from start_port."""
    for p in range(start_port, start_port + max_attempts):
        if is_port_available(p, host):
            return p
    # Fallback to OS assigned port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]

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
            super().finish_request(request, client_address)
        except Exception:
            pass


class ZipStreamWebHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _set_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Range, Content-Type, Accept, Origin, User-Agent")
        self.send_header("Access-Control-Expose-Headers", "Content-Range, Content-Length, Accept-Ranges")

    def do_OPTIONS(self):
        if self.path == "/webdav" or self.path.startswith("/webdav/"):
            self.send_response(200)
            self._set_cors_headers()
            for k, v in WebDAVBridge.get_dav_headers().items():
                self.send_header(k, v)
            self.send_header("Content-Length", "0")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            return
        self.send_response(204)
        self._set_cors_headers()
        self.send_header("Content-Length", "0")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

    def do_PROPFIND(self):
        self._handle_webdav_propfind()

    def do_HEAD(self):
        if self.path == "/webdav" or self.path.startswith("/webdav/"):
            self._handle_webdav_head()
        elif self.path.startswith("/stream/"):
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
            # Resolve static web GUI path cleanly within ZipStreamHub or fallback
            base_dir = os.path.dirname(os.path.abspath(__file__))
            static_html = os.path.join(base_dir, "static", "web_gui.html")
            local_html = os.path.join(base_dir, "web_gui.html")
            fallback_html = r"E:\Mermis\web_gui.html"
            
            if os.path.exists(static_html):
                gui_path = static_html
            elif os.path.exists(local_html):
                gui_path = local_html
            else:
                gui_path = fallback_html
                
            self._serve_file(gui_path, "text/html")
        elif self.path == "/api/ping" or self.path.startswith("/api/ping?"):
            self._handle_api_ping()
        elif self.path == "/webdav" or self.path.startswith("/webdav/"):
            self._handle_webdav_get()
        elif self.path == "/api/players":
            self._handle_api_players()
        elif self.path == "/api/stats" or self.path.startswith("/api/stats"):
            self._handle_api_stats_get()
        elif self.path == "/api/config":
            self._handle_api_config_get()
        elif self.path == "/api/history" or self.path.startswith("/api/history?"):
            self._handle_api_history_get()
        elif self.path.startswith("/api/playlist.m3u"):
            self._handle_api_playlist()
        elif self.path.startswith("/api/strm.zip") or self.path.startswith("/api/strm"):
            self._handle_api_strm_bundle()
        elif self.path.startswith("/api/media_inspect") or self.path.startswith("/api/probe"):
            self._handle_api_media_inspect()
        elif self.path.startswith("/api/subtitle"):
            self._handle_api_subtitle()
        elif self.path.startswith("/stream/"):
            self._handle_stream_get()
        else:
            self.send_response(404)
            self._set_cors_headers()
            self.end_headers()

    def do_POST(self):
        if self.path == "/api/inspect":
            self._handle_api_inspect()
        elif self.path == "/api/config":
            self._handle_api_config_post()
        elif self.path == "/api/play":
            self._handle_api_play()
        elif self.path == "/api/history/favorite":
            self._handle_api_history_favorite()
        else:
            self.send_response(404)
            self._set_cors_headers()
            self.end_headers()

    def do_DELETE(self):
        if self.path == "/api/history" or self.path.startswith("/api/history?"):
            self._handle_api_history_delete()
        else:
            self.send_response(404)
            self._set_cors_headers()
            self.end_headers()

    def _serve_file(self, filepath: str, content_type: str):
        try:
            if not os.path.exists(filepath):
                self.send_response(404)
                self._set_cors_headers()
                self.end_headers()
                self.wfile.write(b"UI file not found.")
                return

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

            # Record in history
            try:
                history.add_history(
                    url=zip_url,
                    title=os.path.basename(zip_url.split("?")[0]) or zip_url,
                    size_bytes=reader.total_size,
                    file_count=len(reader.entries),
                )
            except Exception:
                pass

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
            import traceback
            traceback.print_exc()
            err_bytes = json.dumps({"status": "error", "error": str(e)}).encode("utf-8")
            self.send_response(500)
            self._set_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(err_bytes)))
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            self.wfile.write(err_bytes)

    def _handle_api_ping(self):
        try:
            port = self.server.server_port if hasattr(self.server, "server_port") else PORT
            resp = {
                "status": "ok",
                "app": "zipstream-hub",
                "version": getattr(sys.modules.get("src.zipstream") or sys.modules.get("zipstream"), "__version__", "1.0.0"),
                "pid": os.getpid(),
                "uptime": round(time.time() - SERVER_START_TIME, 2),
                "port": port
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

    def _handle_api_stats_get(self):
        try:
            stats = get_streaming_metrics()
            resp = {
                "status": "ok",
                "stats": stats
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

    def _handle_api_players(self):
        try:
            players = get_installed_players()
            resp = {
                "status": "ok",
                "players": list(players.values()),
                "default_player": next((k for k in ["potplayer", "vlc", "mpv", "mpc-hc", "mpc-be", "iina", "browser"] if k in players), "browser")
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

    def _handle_api_config_get(self):
        try:
            cfg = load_config()
            resp = {
                "status": "ok",
                "config": cfg.to_dict()
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

    def _handle_api_config_post(self):
        length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(length) if length > 0 else b"{}"
        try:
            body = json.loads(post_data.decode("utf-8")) if post_data else {}
            cfg = load_config()

            streaming_update = body.get("streaming", {})
            if "prefetch_buffer_size_mb" in streaming_update:
                cfg.streaming.prefetch_buffer_size_mb = max(1, int(streaming_update["prefetch_buffer_size_mb"]))
            if "slice_size_kb" in streaming_update:
                cfg.streaming.slice_size_kb = max(8, int(streaming_update["slice_size_kb"]))
            if "chunk_timeout_seconds" in streaming_update:
                cfg.streaming.chunk_timeout_seconds = max(1, int(streaming_update["chunk_timeout_seconds"]))
            if "max_concurrent_streams" in streaming_update:
                cfg.streaming.max_concurrent_streams = max(1, int(streaming_update["max_concurrent_streams"]))

            # Save to config.json
            cfg.save()

            resp = {
                "status": "ok",
                "message": "Configuration updated successfully",
                "config": cfg.to_dict()
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

    def _handle_api_history_get(self):
        try:
            parsed = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(parsed.query)
            limit_str = qs.get("limit", ["20"])[0]
            fav_str = qs.get("favorites_only", ["0"])[0]
            limit = int(limit_str) if limit_str.isdigit() else 20
            favorites_only = fav_str.lower() in ("1", "true", "yes")

            items = history.get_history(limit=limit)
            if favorites_only:
                items = [item for item in items if item.get("is_favorite")]

            resp = {
                "status": "ok",
                "history": items,
                "count": len(items)
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

    def _handle_api_history_favorite(self):
        length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(length) if length > 0 else b"{}"
        try:
            body = json.loads(post_data.decode("utf-8")) if post_data else {}
            url = body.get("url", "").strip()
            if not url:
                parsed = urllib.parse.urlparse(self.path)
                qs = urllib.parse.parse_qs(parsed.query)
                url = qs.get("url", [""])[0].strip()

            if not url:
                raise ValueError("Missing 'url' parameter")

            is_favorite = history.toggle_favorite(url)
            resp = {
                "status": "ok",
                "url": url,
                "is_favorite": is_favorite
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
            self.send_response(400)
            self._set_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(err_bytes)))
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            self.wfile.write(err_bytes)

    def _handle_api_history_delete(self):
        try:
            parsed = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(parsed.query)
            url = qs.get("url", [""])[0].strip()

            if not url:
                length = int(self.headers.get("Content-Length", 0))
                if length > 0:
                    body = json.loads(self.rfile.read(length).decode("utf-8"))
                    url = body.get("url", "").strip()

            if not url:
                raise ValueError("Missing 'url' parameter")

            deleted = history.delete_history(url)
            resp = {
                "status": "ok",
                "url": url,
                "deleted": deleted
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
            self.send_response(400)
            self._set_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(err_bytes)))
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            self.wfile.write(err_bytes)

    def _handle_api_playlist(self):
        try:
            parsed = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(parsed.query)
            query_url = qs.get("url", [""])[0].strip()

            server_port = getattr(self.server, "server_port", PORT)
            host_header = self.headers.get("Host", f"127.0.0.1:{server_port}")
            base_url = f"http://{host_header}"
            
            with ARCHIVE_LOCK:
                if query_url:
                    if query_url in READERS_BY_URL:
                        reader = READERS_BY_URL[query_url]
                    else:
                        reader = RemoteZipReader(query_url)
                        READERS_BY_URL[query_url] = reader
                    entries = reader.entries
                else:
                    reader = CURRENT_READER
                    entries = list(CACHED_ENTRIES.values()) if CACHED_ENTRIES else (reader.entries if reader else [])

            # Filter to video files only
            video_entries = [ep for ep in entries if is_video_file(ep.get("name", ""))]
            if not video_entries and entries:
                # If none explicitly identified by extension, check if any entry exists
                video_entries = entries

            if not video_entries:
                self.send_response(400)
                self._set_cors_headers()
                self.end_headers()
                self.wfile.write(b"#EXTM3U\n# No active or queried archive video entries found.\n")
                return

            lines = ["#EXTM3U", "#EXT-X-VERSION:3", f"# PLAYLIST GENERATED BY ZIPSTREAM HUB ({len(video_entries)} items)"]
            for ep in sorted(video_entries, key=lambda x: x["id"]):
                duration = -1
                name = ep.get("name", f"Track {ep['id']}")
                encoded_name = urllib.parse.quote(name)
                stream_link = f"{base_url}/stream/{ep['id']}/{encoded_name}"
                lines.append(f'#EXTINF:{duration} tvg-name="{name}" group-title="ZipStream Hub",{name}')
                lines.append(stream_link)

            playlist_content = "\n".join(lines).encode("utf-8")
            self.send_response(200)
            self._set_cors_headers()
            self.send_header("Content-Type", "application/x-mpegurl; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="zipstream_playlist.m3u"')
            self.send_header("Content-Length", str(len(playlist_content)))
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            self.wfile.write(playlist_content)
        except Exception as e:
            self.send_response(500)
            self._set_cors_headers()
            self.end_headers()
            self.wfile.write(str(e).encode("utf-8"))

    def _handle_api_strm_bundle(self):
        """
        Generates and serves an in-memory ZIP package containing .strm virtual files for Jellyfin/Emby/Kodi.
        Format: /api/strm.zip or /api/strm?url=<zip_url>&structure=<auto|flat|mirror>
        """
        try:
            parsed = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(parsed.query)
            query_url = qs.get("url", [""])[0].strip()
            structure_type = qs.get("structure", ["auto"])[0].strip()

            server_port = getattr(self.server, "server_port", PORT)
            host_header = self.headers.get("Host", f"127.0.0.1:{server_port}")
            base_url = f"http://{host_header}"

            with ARCHIVE_LOCK:
                if query_url:
                    if query_url in READERS_BY_URL:
                        reader = READERS_BY_URL[query_url]
                    else:
                        reader = RemoteZipReader(query_url)
                        READERS_BY_URL[query_url] = reader
                    entries = reader.entries
                else:
                    reader = CURRENT_READER
                    entries = list(CACHED_ENTRIES.values()) if CACHED_ENTRIES else (reader.entries if reader else [])

            video_entries = [ep for ep in entries if is_video_file(ep.get("name", ""))]
            if not video_entries and entries:
                video_entries = entries

            if not video_entries:
                self.send_response(400)
                self._set_cors_headers()
                self.end_headers()
                self.wfile.write(b"No active or queried archive video entries found for STRM export.")
                return

            zip_bytes = generate_strm_zip_bundle(video_entries, base_url, structure_type=structure_type)
            self.send_response(200)
            self._set_cors_headers()
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", 'attachment; filename="zipstream_strm_library.zip"')
            self.send_header("Content-Length", str(len(zip_bytes)))
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            self.wfile.write(zip_bytes)
        except Exception as e:
            self.send_response(500)
            self._set_cors_headers()
            self.end_headers()
            self.wfile.write(str(e).encode("utf-8"))

    def _handle_api_media_inspect(self):
        """
        Extracts video/audio track metadata (codecs, resolution, container) via fast Range inspection.
        Format: /api/media_inspect?id=<entry_id>&url=<zip_url>
        """
        try:
            parsed = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(parsed.query)
            ep_id_str = qs.get("id", [""])[0].strip()
            query_url = qs.get("url", [""])[0].strip()

            with ARCHIVE_LOCK:
                if query_url:
                    if query_url in READERS_BY_URL:
                        reader = READERS_BY_URL[query_url]
                    else:
                        reader = RemoteZipReader(query_url)
                        READERS_BY_URL[query_url] = reader
                    cached = {e["id"]: e for e in reader.entries}
                else:
                    reader = CURRENT_READER
                    cached = dict(CACHED_ENTRIES)

            if not reader or not cached:
                self.send_response(404)
                self._set_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "error": "No active archive."}).encode("utf-8"))
                return

            target_entry = None
            if ep_id_str.isdigit():
                target_entry = cached.get(int(ep_id_str))

            if not target_entry:
                self.send_response(404)
                self._set_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "error": "Media entry not found."}).encode("utf-8"))
                return

            media_info = inspect_media_header(reader, target_entry)
            resp = {
                "status": "ok",
                "entry_id": target_entry.get("id"),
                "name": target_entry.get("name"),
                "media_info": media_info
            }
            resp_bytes = json.dumps(resp).encode("utf-8")
            self.send_response(200)
            self._set_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp_bytes)))
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            self.wfile.write(resp_bytes)
        except Exception as e:
            err_bytes = json.dumps({"status": "error", "error": str(e)}).encode("utf-8")
            self.send_response(500)
            self._set_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(err_bytes)))
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            self.wfile.write(err_bytes)

    def _handle_api_subtitle(self):
        """
        Extracts subtitle text (.srt / .vtt / .ass / .ssa) from the archive and converts to WebVTT on the fly.
        Format: /api/subtitle?id=<id>&name=<sub_name>&url=<archive_url>
        """
        try:
            parsed = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(parsed.query)
            
            ep_id_str = qs.get("id", [""])[0]
            sub_name = qs.get("name", [""])[0]
            query_url = qs.get("url", [""])[0].strip()

            with ARCHIVE_LOCK:
                if query_url:
                    if query_url in READERS_BY_URL:
                        reader = READERS_BY_URL[query_url]
                    else:
                        reader = RemoteZipReader(query_url)
                        READERS_BY_URL[query_url] = reader
                    cached = {e["id"]: e for e in reader.entries}
                else:
                    reader = CURRENT_READER
                    cached = dict(CACHED_ENTRIES)

            if not reader or not cached:
                self.send_response(404)
                self._set_cors_headers()
                self.end_headers()
                self.wfile.write(b"No active archive.")
                return

            target_entry = None
            if ep_id_str.isdigit():
                target_entry = cached.get(int(ep_id_str))
            
            if not target_entry and sub_name:
                for e in cached.values():
                    if e["name"].lower() == sub_name.lower():
                        target_entry = e
                        break

            if not target_entry:
                self.send_response(404)
                self._set_cors_headers()
                self.end_headers()
                self.wfile.write(b"Subtitle entry not found.")
                return

            # Read subtitle bytes efficiently via Range request without reading whole archive
            sub_bytes = reader.read_entry_bytes(target_entry)
            text = sub_bytes.decode("utf-8", errors="replace")

            # Convert to WebVTT using subtitle_parser
            vtt_text = convert_to_vtt(text, target_entry.get("name", ""))
            vtt_bytes = vtt_text.encode("utf-8")

            self.send_response(200)
            self._set_cors_headers()
            self.send_header("Content-Type", "text/vtt; charset=utf-8")
            self.send_header("Content-Length", str(len(vtt_bytes)))
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            self.wfile.write(vtt_bytes)
        except Exception as e:
            self.send_response(500)
            self._set_cors_headers()
            self.end_headers()
            self.wfile.write(str(e).encode("utf-8"))

    def _handle_api_play(self):
        length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(length)
        try:
            body = json.loads(post_data.decode("utf-8"))
            stream_url = body.get("url")
            requested_player = body.get("player")

            if not stream_url:
                raise ValueError("Missing 'url' parameter")

            result = launch_stream(player_key=requested_player, stream_url=stream_url)

            resp_status = 200 if result.get("success") else 400
            resp_bytes = json.dumps(result).encode("utf-8")

            self.send_response(resp_status)
            self._set_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp_bytes)))
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            self.wfile.write(resp_bytes)
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

        # High-Throughput Read-Ahead Prefetch Buffer with Connection Pooling & Memory Safety
        cfg = load_config()
        prefetcher = StreamPrefetcher(
            url=reader.url,
            start_byte=remote_start,
            end_byte=remote_end,
            pool=getattr(reader, "pool", None) or HTTP_POOL,
            buffer_size_mb=cfg.streaming.prefetch_buffer_size_mb,
            slice_size_kb=cfg.streaming.slice_size_kb,
            filename=entry.get("name")
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

    def _handle_webdav_propfind(self):
        try:
            depth = self.headers.get("Depth", "1")
            with ARCHIVE_LOCK:
                node_type, entry, reader = WebDAVBridge.resolve_entry(
                    self.path,
                    READERS_BY_URL,
                    CURRENT_READER,
                    CACHED_ENTRIES
                )

            if node_type == "not_found":
                self.send_response(404)
                self._set_cors_headers()
                self.end_headers()
                return

            server_port = getattr(self.server, "server_port", PORT)
            host_hdr = self.headers.get("Host", f"127.0.0.1:{server_port}")
            host_prefix = f"http://{host_hdr}"
            xml_data = WebDAVBridge.build_propfind_xml(
                req_path=self.path,
                node_type=node_type,
                target_entry=entry,
                reader=reader,
                depth=depth,
                host_prefix=host_prefix
            )

            self.send_response(207)
            self._set_cors_headers()
            for k, v in WebDAVBridge.get_dav_headers().items():
                self.send_header(k, v)
            self.send_header("Content-Type", 'application/xml; charset="utf-8"')
            self.send_header("Content-Length", str(len(xml_data)))
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            self.wfile.write(xml_data)
        except Exception as e:
            self.send_response(500)
            self._set_cors_headers()
            self.end_headers()
            self.wfile.write(str(e).encode("utf-8"))

    def _handle_webdav_head(self):
        with ARCHIVE_LOCK:
            node_type, entry, reader = WebDAVBridge.resolve_entry(
                self.path,
                READERS_BY_URL,
                CURRENT_READER,
                CACHED_ENTRIES
            )

        if node_type == "not_found":
            self.send_response(404)
            self._set_cors_headers()
            self.end_headers()
            return

        if node_type == "root":
            self.send_response(200)
            self._set_cors_headers()
            for k, v in WebDAVBridge.get_dav_headers().items():
                self.send_header(k, v)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            return

        # File node
        total_file_size = entry["size_bytes"]
        mime_type = self._get_mime_type(entry["name"])

        self.send_response(200)
        self._set_cors_headers()
        for k, v in WebDAVBridge.get_dav_headers().items():
            self.send_header(k, v)
        self.send_header("Content-Type", mime_type)
        self.send_header("Content-Length", str(total_file_size))
        self.send_header("Connection", "keep-alive")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

    def _handle_webdav_get(self):
        with ARCHIVE_LOCK:
            node_type, entry, reader = WebDAVBridge.resolve_entry(
                self.path,
                READERS_BY_URL,
                CURRENT_READER,
                CACHED_ENTRIES
            )

        if node_type == "not_found":
            self.send_response(404)
            self._set_cors_headers()
            self.end_headers()
            return

        if node_type == "root":
            server_port = getattr(self.server, "server_port", PORT)
            host_hdr = self.headers.get("Host", f"127.0.0.1:{server_port}")
            base_url = f"http://{host_hdr}"
            html_bytes = WebDAVBridge.build_html_directory(self.path, reader, base_url)
            self.send_response(200)
            self._set_cors_headers()
            for k, v in WebDAVBridge.get_dav_headers().items():
                self.send_header(k, v)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html_bytes)))
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            self.wfile.write(html_bytes)
            return

        # Stream the entry transparently via get_data_offset and prefetcher
        if not entry or not reader:
            self.send_response(404)
            self._set_cors_headers()
            self.end_headers()
            return

        try:
            data_start = reader.get_data_offset(entry)
        except Exception:
            self.send_response(500)
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
        for k, v in WebDAVBridge.get_dav_headers().items():
            self.send_header(k, v)
        self.send_header("Content-Type", mime_type)
        self.send_header("Content-Length", str(content_length))
        if status_code == 206:
            self.send_header("Content-Range", f"bytes {start_byte}-{end_byte}/{total_file_size}")
        self.send_header("Connection", "keep-alive")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        cfg = load_config()
        prefetcher = StreamPrefetcher(
            url=reader.url,
            start_byte=remote_start,
            end_byte=remote_end,
            pool=getattr(reader, "pool", None) or HTTP_POOL,
            buffer_size_mb=cfg.streaming.prefetch_buffer_size_mb,
            slice_size_kb=cfg.streaming.slice_size_kb
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


# Backward compatibility aliases
ThreadedHTTPServer = ThreadedZipStreamServer
ZipStreamHandler = ZipStreamWebHandler


def start_stream_server(url: str, episode_index: int = 1):
    """
    Directly binds and serves an archive entry for single-file streaming CLI scripts.
    """
    global CURRENT_READER, CACHED_ENTRIES, READERS_BY_URL
    reader = RemoteZipReader(url)
    with ARCHIVE_LOCK:
        CURRENT_READER = reader
        CACHED_ENTRIES = {e["id"]: e for e in reader.entries}
        READERS_BY_URL[url] = reader

    if episode_index < 1 or episode_index > len(reader.entries):
        raise ValueError(f"Invalid episode index. Available: 1 to {len(reader.entries)}")

    entry = reader.entries[episode_index - 1]
    server_address = ("127.0.0.1", PORT)
    httpd = ThreadedZipStreamServer(server_address, ZipStreamWebHandler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


def check_running_instance(port: int = PORT) -> Optional[dict]:
    """
    Perform an instant HTTP handshake with localhost on the specified port.
    Returns the ping response dict if ZipStream Hub is already running, or None.
    """
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/ping", method="GET")
        with urllib.request.urlopen(req, timeout=0.8) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("app") == "zipstream-hub":
                    return data
    except Exception:
        pass
    return None


def run_server(port: int = PORT, auto_port: bool = False):
    existing = check_running_instance(port)
    if existing:
        pid = existing.get("pid", "unknown")
        ver = existing.get("version", "1.0.0")
        uptime = existing.get("uptime", 0)
        actual_port = existing.get("port", port)
        save_active_port(actual_port)
        print(f"[ZipStream Hub] Auto-attached to already running instance on http://127.0.0.1:{actual_port} (PID: {pid}, v{ver}, Uptime: {uptime}s).")
        return

    actual_port = port
    if auto_port and not is_port_available(actual_port):
        actual_port = find_free_port(start_port=port)
        print(f"[ZipStream Hub] Port {port} occupied. Auto-hunted next available port: {actual_port}")

    server_address = ("127.0.0.1", actual_port)
    try:
        httpd = ThreadedZipStreamServer(server_address, ZipStreamWebHandler)
    except OSError as e:
        # Re-check in case another process just bound right before us
        existing = check_running_instance(actual_port)
        if existing:
            pid = existing.get("pid", "unknown")
            ver = existing.get("version", "1.0.0")
            save_active_port(actual_port)
            print(f"[ZipStream Hub] Auto-attached to already running instance on http://127.0.0.1:{actual_port} (PID: {pid}, v{ver}).")
            return
        if auto_port:
            actual_port = find_free_port(start_port=actual_port + 1)
            server_address = ("127.0.0.1", actual_port)
            httpd = ThreadedZipStreamServer(server_address, ZipStreamWebHandler)
        else:
            raise e

    # Persist the dynamic active port for Web GUI and Control Panel
    save_active_port(actual_port)

    print(f"ZipStream Hub (High-Performance Engine) running on http://127.0.0.1:{actual_port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down ZipStream Hub...")
    finally:
        remove_active_port_file()
        httpd.server_close()


def parse_args():
    parser = argparse.ArgumentParser(description="ZipStream Hub HTTP / WebDAV Streaming Server")
    parser.add_argument("--port", type=int, default=PORT, help=f"Port to bind the server to (default: {PORT})")
    parser.add_argument("--auto-port", action="store_true", help="Automatically hunt next free port (8788, 8789...) if requested port is in use")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_server(port=args.port, auto_port=args.auto_port)
