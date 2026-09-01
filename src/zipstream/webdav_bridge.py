import os
import sys
import html
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

try:
    from .engine import RemoteZipReader, StreamPrefetcher, HTTP_POOL
    from .config import load_config
except ImportError:
    from engine import RemoteZipReader, StreamPrefetcher, HTTP_POOL
    from config import load_config

class WebDAVBridge:
    """
    Lightweight WebDAV and HTTP Directory Bridge for ZipStreamHub.
    - Implements WebDAV (RFC 4918) PROPFIND, OPTIONS, HEAD, GET.
    - Implements standard HTML directory listing for standard web browsers.
    - Maps direct file requests transparently to RemoteZipReader and range prefetching engine.
    - Compatible with Infuse, Kodi, VLC, PotPlayer, and Windows File Explorer (Map Network Drive).
    """

    DAV_HEADER = "1, 2"
    DAV_METHODS = "OPTIONS, GET, HEAD, PROPFIND"

    def __init__(self):
        pass

    @staticmethod
    def get_dav_headers() -> Dict[str, str]:
        return {
            "DAV": WebDAVBridge.DAV_HEADER,
            "MS-Author-Via": "DAV",
            "Allow": WebDAVBridge.DAV_METHODS,
            "Accept-Ranges": "bytes",
        }

    @staticmethod
    def format_http_date(dt: Optional[datetime] = None) -> str:
        if dt is None:
            dt = datetime.now(timezone.utc)
        elif dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.strftime("%a, %d %b %Y %H:%M:%S GMT")

    @staticmethod
    def format_iso8601(dt: Optional[datetime] = None) -> str:
        if dt is None:
            dt = datetime.now(timezone.utc)
        elif dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    @staticmethod
    def resolve_entry(
        path: str,
        readers_by_url: Dict[str, RemoteZipReader],
        current_reader: Optional[RemoteZipReader],
        cached_entries: Dict[int, dict]
    ) -> Tuple[str, Optional[dict], Optional[RemoteZipReader]]:
        """
        Parses request path and resolves target.
        Returns (node_type, entry_dict, reader)
        node_type can be:
          - 'root': /webdav or /webdav/
          - 'file': matched entry by ID or filename
          - 'not_found': entry could not be resolved
        """
        clean_path = urllib.parse.unquote(path.split("?")[0])
        
        # Normalize trailing slashes
        prefix = "/webdav"
        if not clean_path.startswith(prefix):
            return "not_found", None, None

        subpath = clean_path[len(prefix):].strip("/")
        if not subpath:
            return "root", None, current_reader

        # 1. Check if subpath is an entry ID like /webdav/1 or /webdav/1/filename.mkv
        parts = subpath.split("/")
        if parts[0].isdigit():
            ep_id = int(parts[0])
            if current_reader and ep_id in cached_entries:
                return "file", cached_entries[ep_id], current_reader

        # 2. Check if subpath matches entry by exact full_path or filename
        if current_reader:
            for entry in current_reader.entries:
                if entry["name"].lower() == subpath.lower() or entry["full_path"].lower() == subpath.lower():
                    return "file", entry, current_reader

        return "not_found", None, current_reader

    @staticmethod
    def build_propfind_xml(
        req_path: str,
        node_type: str,
        target_entry: Optional[dict],
        reader: Optional[RemoteZipReader],
        depth: str = "1",
        host_prefix: str = "http://127.0.0.1:8787"
    ) -> bytes:
        """
        Constructs standard RFC 4918 multistatus XML response for PROPFIND.
        """
        now_http = WebDAVBridge.format_http_date()
        now_iso = WebDAVBridge.format_iso8601()

        clean_path = urllib.parse.unquote(req_path.split("?")[0]).rstrip("/")
        if not clean_path:
            clean_path = "/webdav"

        # XML Multi-Status Root
        xml_lines = [
            '<?xml version="1.0" encoding="utf-8"?>',
            '<D:multistatus xmlns:D="DAV:">'
        ]

        def add_collection_node(href_path: str, display_name: str):
            encoded_href = urllib.parse.quote(href_path, safe="/:")
            if not encoded_href.endswith("/"):
                encoded_href += "/"
            xml_lines.append(f"""  <D:response>
    <D:href>{encoded_href}</D:href>
    <D:propstat>
      <D:prop>
        <D:displayname>{html.escape(display_name)}</D:displayname>
        <D:resourcetype><D:collection/></D:resourcetype>
        <D:getlastmodified>{now_http}</D:getlastmodified>
        <D:creationdate>{now_iso}</D:creationdate>
      </D:prop>
      <D:status>HTTP/1.1 200 OK</D:status>
    </D:propstat>
  </D:response>""")

        def add_file_node(href_path: str, entry: dict):
            encoded_href = urllib.parse.quote(href_path, safe="/:")
            size = entry.get("size_bytes", 0)
            name = entry.get("name", "file")
            
            # Simple MIME detection
            lower = name.lower()
            if lower.endswith(".mkv"):
                mime = "video/x-matroska"
            elif lower.endswith(".mp4"):
                mime = "video/mp4"
            elif lower.endswith(".webm"):
                mime = "video/webm"
            elif lower.endswith(".avi"):
                mime = "video/x-msvideo"
            elif lower.endswith(".ts"):
                mime = "video/mp2t"
            elif lower.endswith(".mov"):
                mime = "video/quicktime"
            elif lower.endswith((".srt", ".vtt", ".ass", ".ssa")):
                mime = "text/plain"
            elif lower.endswith((".mp3", ".flac", ".m4a", ".aac")):
                mime = "audio/mpeg"
            else:
                mime = "application/octet-stream"

            xml_lines.append(f"""  <D:response>
    <D:href>{encoded_href}</D:href>
    <D:propstat>
      <D:prop>
        <D:displayname>{html.escape(name)}</D:displayname>
        <D:resourcetype/>
        <D:getcontentlength>{size}</D:getcontentlength>
        <D:getcontenttype>{mime}</D:getcontenttype>
        <D:getlastmodified>{now_http}</D:getlastmodified>
        <D:creationdate>{now_iso}</D:creationdate>
        <D:supportedlock/>
      </D:prop>
      <D:status>HTTP/1.1 200 OK</D:status>
    </D:propstat>
  </D:response>""")

        if node_type == "root":
            # Add collection node itself
            add_collection_node(clean_path, "WebDAV Archive")
            
            # If depth != 0, add children
            if depth != "0" and reader:
                for entry in reader.entries:
                    child_href = f"{clean_path}/{entry['id']}/{entry['name']}"
                    add_file_node(child_href, entry)

        elif node_type == "file" and target_entry:
            add_file_node(clean_path, target_entry)

        xml_lines.append("</D:multistatus>")
        return "\n".join(xml_lines).encode("utf-8")

    @staticmethod
    def build_html_directory(
        req_path: str,
        reader: Optional[RemoteZipReader],
        base_url: str = "http://127.0.0.1:8787"
    ) -> bytes:
        """
        Generates clean, responsive HTML index page for browser access at /webdav/.
        """
        clean_path = urllib.parse.unquote(req_path.split("?")[0])
        entries = reader.entries if reader else []
        archive_name = os.path.basename(reader.url.split("?")[0]) if (reader and reader.url) else "No Active Archive"

        table_rows = []
        if not entries:
            table_rows.append('<tr><td colspan="4" style="text-align:center; padding: 24px; color: #888;">No active archive loaded. Inspect a ZIP URL first in the Web Dashboard.</td></tr>')
        else:
            for ep in entries:
                encoded_name = urllib.parse.quote(ep['name'])
                href = f"/webdav/{ep['id']}/{encoded_name}"
                stream_href = f"/stream/{ep['id']}/{encoded_name}"
                size_str = f"{ep.get('size_mb', 0)} MB" if ep.get('size_mb', 0) < 1024 else f"{ep.get('size_gb', 0)} GB"
                method = ep.get("method_name", "STORE")
                table_rows.append(f"""
                <tr>
                    <td><a href="{href}" class="file-link">📄 {html.escape(ep['name'])}</a></td>
                    <td class="size-col">{size_str}</td>
                    <td class="method-col"><span class="badge">{method}</span></td>
                    <td class="action-col">
                        <a href="{stream_href}" class="btn-direct">Direct Stream</a>
                    </td>
                </tr>
                """)

        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ZipStreamHub WebDAV Directory - {html.escape(archive_name)}</title>
    <style>
        :root {{
            --bg: #0f172a;
            --surface: #1e293b;
            --border: #334155;
            --text: #f8fafc;
            --text-muted: #94a3b8;
            --primary: #38bdf8;
            --primary-hover: #0ea5e9;
            --accent: #6366f1;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background: var(--bg);
            color: var(--text);
            padding: 32px 20px;
            line-height: 1.5;
        }}
        .container {{
            max-width: 1000px;
            margin: 0 auto;
        }}
        .header {{
            background: var(--surface);
            padding: 24px;
            border-radius: 12px;
            border: 1px solid var(--border);
            margin-bottom: 24px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.2);
        }}
        .title {{
            font-size: 1.5rem;
            font-weight: 700;
            color: var(--primary);
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 8px;
        }}
        .subtitle {{
            color: var(--text-muted);
            font-size: 0.95rem;
        }}
        .info-card {{
            background: rgba(56, 189, 248, 0.08);
            border-left: 4px solid var(--primary);
            padding: 12px 16px;
            border-radius: 6px;
            margin-top: 16px;
            font-size: 0.9rem;
            color: #bae6fd;
        }}
        .info-card code {{
            background: rgba(0, 0, 0, 0.3);
            padding: 2px 6px;
            border-radius: 4px;
            font-family: monospace;
            color: #fff;
        }}
        .table-wrap {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.2);
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            text-align: left;
        }}
        th {{
            background: #182234;
            padding: 14px 18px;
            font-weight: 600;
            font-size: 0.85rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--text-muted);
            border-bottom: 1px solid var(--border);
        }}
        td {{
            padding: 14px 18px;
            border-bottom: 1px solid rgba(51, 65, 85, 0.5);
            font-size: 0.95rem;
        }}
        tr:last-child td {{
            border-bottom: none;
        }}
        tr:hover td {{
            background: rgba(255, 255, 255, 0.02);
        }}
        .file-link {{
            color: var(--text);
            text-decoration: none;
            font-weight: 500;
            display: inline-block;
            transition: color 0.15s;
        }}
        .file-link:hover {{
            color: var(--primary);
            text-decoration: underline;
        }}
        .size-col {{
            color: var(--text-muted);
            font-family: monospace;
            white-space: nowrap;
        }}
        .badge {{
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            background: #334155;
            color: #94a3b8;
            font-size: 0.75rem;
            font-weight: 600;
        }}
        .btn-direct {{
            display: inline-block;
            padding: 4px 10px;
            background: rgba(56, 189, 248, 0.15);
            color: var(--primary);
            border-radius: 6px;
            text-decoration: none;
            font-size: 0.8rem;
            font-weight: 600;
            transition: all 0.2s;
        }}
        .btn-direct:hover {{
            background: var(--primary);
            color: #0f172a;
        }}
        .footer {{
            margin-top: 24px;
            text-align: center;
            color: var(--text-muted);
            font-size: 0.85rem;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="title">
                <span>📁</span> ZipStreamHub WebDAV & HTTP Index
            </div>
            <div class="subtitle">
                Current Archive: <strong>{html.escape(archive_name)}</strong> ({len(entries)} items)
            </div>
            <div class="info-card">
                💡 <strong>Client Connection Info:</strong> Map WebDAV Network Drive or connect Infuse / Kodi / VLC to <code>{base_url}/webdav/</code>
            </div>
        </div>

        <div class="table-wrap">
            <table>
                <thead>
                    <tr>
                        <th>File Name</th>
                        <th>Size</th>
                        <th>Method</th>
                        <th>Stream</th>
                    </tr>
                </thead>
                <tbody>
                    {"".join(table_rows)}
                </tbody>
            </table>
        </div>

        <div class="footer">
            ZipStreamHub v2.4 • High-Throughput Remote ZIP & ZIP64 Streaming Engine
        </div>
    </div>
</body>
</html>
"""
        return html_content.encode("utf-8")
