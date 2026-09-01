import io
import json
import threading
import time
import xml.etree.ElementTree as ET
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from unittest.mock import MagicMock

from webdav_bridge import WebDAVBridge
from engine import RemoteZipReader


def create_fake_reader():
    reader = MagicMock(spec=RemoteZipReader)
    reader.url = "http://example.com/test_archive.zip"
    reader.total_size = 100000000
    reader.entries = [
        {
            "id": 1,
            "name": "Episode01.mkv",
            "full_path": "Season1/Episode01.mkv",
            "method": 0,
            "method_name": "STORE",
            "size_bytes": 50000000,
            "comp_size_bytes": 50000000,
            "size_gb": 0.05,
            "size_mb": 47.7,
            "local_header_offset": 100,
            "data_offset": 200
        },
        {
            "id": 2,
            "name": "Episode02.mp4",
            "full_path": "Season1/Episode02.mp4",
            "method": 0,
            "method_name": "STORE",
            "size_bytes": 45000000,
            "comp_size_bytes": 45000000,
            "size_gb": 0.04,
            "size_mb": 42.9,
            "local_header_offset": 50000300,
            "data_offset": 50000400
        }
    ]
    reader.get_data_offset.side_effect = lambda entry: entry["data_offset"]
    return reader


def test_webdav_resolve_entry_root():
    reader = create_fake_reader()
    cached = {e["id"]: e for e in reader.entries}
    readers = {reader.url: reader}

    node_type, entry, r = WebDAVBridge.resolve_entry("/webdav/", readers, reader, cached)
    assert node_type == "root"
    assert entry is None
    assert r == reader

    node_type, entry, r = WebDAVBridge.resolve_entry("/webdav", readers, reader, cached)
    assert node_type == "root"


def test_webdav_resolve_entry_by_id():
    reader = create_fake_reader()
    cached = {e["id"]: e for e in reader.entries}
    readers = {reader.url: reader}

    node_type, entry, r = WebDAVBridge.resolve_entry("/webdav/1", readers, reader, cached)
    assert node_type == "file"
    assert entry["id"] == 1
    assert entry["name"] == "Episode01.mkv"

    node_type, entry, r = WebDAVBridge.resolve_entry("/webdav/2/Episode02.mp4", readers, reader, cached)
    assert node_type == "file"
    assert entry["id"] == 2


def test_webdav_resolve_entry_by_filename():
    reader = create_fake_reader()
    cached = {e["id"]: e for e in reader.entries}
    readers = {reader.url: reader}

    node_type, entry, r = WebDAVBridge.resolve_entry("/webdav/Episode01.mkv", readers, reader, cached)
    assert node_type == "file"
    assert entry["id"] == 1


def test_webdav_propfind_xml_root():
    reader = create_fake_reader()
    xml_bytes = WebDAVBridge.build_propfind_xml(
        req_path="/webdav/",
        node_type="root",
        target_entry=None,
        reader=reader,
        depth="1"
    )

    assert b"<D:multistatus" in xml_bytes
    assert b"Episode01.mkv" in xml_bytes
    assert b"Episode02.mp4" in xml_bytes
    assert b"video/x-matroska" in xml_bytes
    assert b"video/mp4" in xml_bytes

    # Parse XML to ensure valid syntax
    root = ET.fromstring(xml_bytes)
    assert root.tag.endswith("multistatus")


def test_webdav_propfind_xml_file():
    reader = create_fake_reader()
    entry = reader.entries[0]
    xml_bytes = WebDAVBridge.build_propfind_xml(
        req_path="/webdav/1/Episode01.mkv",
        node_type="file",
        target_entry=entry,
        reader=reader,
        depth="0"
    )

    assert b"<D:multistatus" in xml_bytes
    assert b"Episode01.mkv" in xml_bytes
    assert b"<D:getcontentlength>50000000</D:getcontentlength>" in xml_bytes

    root = ET.fromstring(xml_bytes)
    assert root.tag.endswith("multistatus")


def test_webdav_html_directory_listing():
    reader = create_fake_reader()
    html_bytes = WebDAVBridge.build_html_directory("/webdav/", reader)

    assert b"ZipStreamHub WebDAV" in html_bytes
    assert b"Episode01.mkv" in html_bytes
    assert b"Episode02.mp4" in html_bytes
    assert b"test_archive.zip" in html_bytes


def test_webdav_server_propfind_multistatus_and_file_stream():
    """Integration test: Launch test server and test WebDAV PROPFIND, GET HTML, and file streaming."""
    import urllib.request
    import server
    from server import ThreadedZipStreamServer, ZipStreamWebHandler

    test_port = 8794
    reader = create_fake_reader()

    # Provide synthetic range content via mock fetch
    raw_file_bytes = b"MOCK_STREAMING_DATA_FOR_WEBDAV_EPISODE_01" * 100
    
    # Mock pool for the reader
    mock_pool = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status = 206
    mock_resp.data = raw_file_bytes[:500]
    mock_pool.request.return_value = mock_resp
    reader.pool = mock_pool
    reader.entries[0]["size_bytes"] = len(raw_file_bytes)

    with server.ARCHIVE_LOCK:
        server.CURRENT_READER = reader
        server.CACHED_ENTRIES = {e["id"]: e for e in reader.entries}
        server.READERS_BY_URL[reader.url] = reader

    httpd = ThreadedZipStreamServer(("127.0.0.1", test_port), ZipStreamWebHandler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    time.sleep(0.2)

    try:
        base = f"http://127.0.0.1:{test_port}"

        # 1. Test PROPFIND request for multistatus XML
        req_propfind = urllib.request.Request(f"{base}/webdav/", method="PROPFIND")
        req_propfind.add_header("Depth", "1")
        with urllib.request.urlopen(req_propfind, timeout=5) as resp:
            assert resp.status == 207
            assert "application/xml" in resp.headers.get("Content-Type", "")
            prop_data = resp.read()
            assert b"<D:multistatus" in prop_data
            assert b"Episode01.mkv" in prop_data
            assert b"Episode02.mp4" in prop_data

        # 2. Test GET directory HTML
        req_get_dir = urllib.request.Request(f"{base}/webdav/")
        with urllib.request.urlopen(req_get_dir, timeout=5) as resp:
            assert resp.status == 200
            assert "text/html" in resp.headers.get("Content-Type", "")
            html_data = resp.read().decode("utf-8")
            assert "ZipStreamHub WebDAV" in html_data
            assert "Episode01.mkv" in html_data

        # 3. Test File stream retrieval via WebDAV endpoint
        req_stream = urllib.request.Request(f"{base}/webdav/1/Episode01.mkv")
        req_stream.add_header("Range", "bytes=0-499")
        with urllib.request.urlopen(req_stream, timeout=5) as resp:
            assert resp.status == 206
            assert resp.headers.get("Accept-Ranges") == "bytes"
            assert "video/x-matroska" in resp.headers.get("Content-Type", "")
            assert resp.headers.get("Content-Range") == f"bytes 0-499/{len(raw_file_bytes)}"
            streamed_body = resp.read()
            assert len(streamed_body) == 500
            assert streamed_body == raw_file_bytes[:500]

        # 4. Test OPTIONS request for DAV headers
        req_opts = urllib.request.Request(f"{base}/webdav/", method="OPTIONS")
        with urllib.request.urlopen(req_opts, timeout=5) as resp:
            assert resp.status == 200
            assert "DAV" in resp.headers
            assert "PROPFIND" in resp.headers.get("Allow", "")

        # 5. Test HEAD request on file
        req_head = urllib.request.Request(f"{base}/webdav/1/Episode01.mkv", method="HEAD")
        with urllib.request.urlopen(req_head, timeout=5) as resp:
            assert resp.status == 200
            assert resp.headers.get("Content-Length") == str(len(raw_file_bytes))
            assert "video/x-matroska" in resp.headers.get("Content-Type", "")
    finally:
        httpd.shutdown()
        httpd.server_close()

