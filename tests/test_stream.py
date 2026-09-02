import io
import json
import time
import socket
import threading
import gc
import urllib3
import pytest
from unittest.mock import MagicMock, patch
from urllib3.response import HTTPResponse

import sys
from pathlib import Path
# Ensure E:\ZipStreamHub is on the python path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import (
    StreamPrefetcher,
    RemoteZipReader,
    HTTP_POOL,
    MetricsTracker,
    METRICS,
    get_streaming_metrics,
    set_bandwidth_limit,
    calculate_adaptive_chunk_size,
)
from server import ZipStreamWebHandler, ThreadedZipStreamServer, ARCHIVE_LOCK, CURRENT_READER, CACHED_ENTRIES, READERS_BY_URL
import server


class MockRangePool:
    """Mock urllib3.PoolManager providing synthetic byte streams with range headers."""
    def __init__(self, data: bytes):
        self.data = data
        self.requests = []

    def request(self, method: str, url: str, headers: dict = None, preload_content: bool = True):
        self.requests.append({"method": method, "url": url, "headers": headers})
        headers = headers or {}
        range_header = headers.get("Range", "")
        
        if not range_header:
            return HTTPResponse(
                body=self.data,
                status=200,
                headers={"Content-Length": str(len(self.data)), "Accept-Ranges": "bytes"}
            )
        
        # bytes=start-end
        range_spec = range_header.replace("bytes=", "").strip()
        parts = range_spec.split("-")
        start = int(parts[0]) if parts[0] else 0
        end = int(parts[1]) if parts[1] else len(self.data) - 1
        end = min(end, len(self.data) - 1)
        
        chunk = self.data[start:end + 1]
        content_range = f"bytes {start}-{end}/{len(self.data)}"
        
        return HTTPResponse(
            body=chunk,
            status=206,
            headers={
                "Content-Range": content_range,
                "Content-Length": str(len(chunk)),
                "Accept-Ranges": "bytes"
            }
        )


def test_offline_mock_range_streaming():
    """Verify StreamPrefetcher correctly slices, buffers, and streams data using mock ranges."""
    total_size = 5 * 1024 * 1024  # 5 MB test payload
    raw_payload = bytes([i % 256 for i in range(total_size)])
    mock_pool = MockRangePool(raw_payload)

    # Test range: 1MB to 3.5MB
    start_byte = 1024 * 1024
    end_byte = int(3.5 * 1024 * 1024) - 1
    expected_data = raw_payload[start_byte:end_byte + 1]

    prefetcher = StreamPrefetcher(
        url="http://mock.test/video.mkv",
        start_byte=start_byte,
        end_byte=end_byte,
        pool=mock_pool
    )
    prefetcher.start()

    collected = bytearray()
    for chunk in prefetcher.stream_chunks():
        collected.extend(chunk)

    assert len(collected) == len(expected_data)
    assert bytes(collected) == expected_data
    prefetcher.close()


def test_stream_prefetcher_socket_slices():
    """Verify prefetcher slices blocks into SOCKET_SLICE_SIZE units."""
    block_size = 512 * 1024  # 512 KB
    payload = b"X" * block_size
    mock_pool = MockRangePool(payload)

    prefetcher = StreamPrefetcher(
        url="http://mock.test/file.dat",
        start_byte=0,
        end_byte=block_size - 1,
        pool=mock_pool
    )
    prefetcher.SOCKET_SLICE_SIZE = 64 * 1024  # 64 KB slices
    prefetcher.BLOCK_SIZE = 128 * 1024
    prefetcher.start()

    slices = list(prefetcher.stream_chunks())
    assert len(slices) == 8  # 512 KB / 64 KB = 8 slices
    for s in slices:
        assert len(s) == 64 * 1024
        assert s == b"X" * (64 * 1024)
    prefetcher.close()


def test_stream_prefetcher_abort_and_cleanup():
    """Verify early abort frees queue and shuts down worker thread cleanly."""
    payload = b"Z" * (10 * 1024 * 1024)  # 10 MB
    mock_pool = MockRangePool(payload)

    prefetcher = StreamPrefetcher(
        url="http://mock.test/large.bin",
        start_byte=0,
        end_byte=len(payload) - 1,
        pool=mock_pool
    )
    prefetcher.start()
    
    # Read just one slice
    gen = prefetcher.stream_chunks()
    first_chunk = next(gen)
    assert len(first_chunk) > 0

    # Trigger close immediately
    prefetcher.close()
    
    # Worker thread should terminate quickly
    if prefetcher.worker_thread:
        prefetcher.worker_thread.join(timeout=1.0)
        assert not prefetcher.worker_thread.is_alive()
    assert prefetcher.queue.empty()


def test_http_206_range_negotiation_handler():
    """Test ZipStreamWebHandler range negotiation logic without binding to a network port."""
    payload = b"0123456789" * 100  # 1000 bytes
    
    mock_reader = MagicMock()
    mock_reader.url = "http://mock.test/test.zip"
    mock_reader.get_data_offset.return_value = 5000
    
    # Test cases: (Range Header, Expected Status, Expected Content-Range, Expected Length)
    cases = [
        (None, 200, None, 1000),
        ("bytes=0-499", 206, "bytes 0-499/1000", 500),
        ("bytes=500-999", 206, "bytes 500-999/1000", 500),
        ("bytes=-200", 206, "bytes 800-999/1000", 200),
        ("bytes=950-", 206, "bytes 950-999/1000", 50),
    ]

    for range_header, expected_status, expected_cr, expected_len in cases:
        mock_socket = MagicMock()
        mock_rfile = io.BytesIO()
        mock_wfile = io.BytesIO()
        
        # Setup server cache state
        with server.ARCHIVE_LOCK:
            server.CURRENT_READER = mock_reader
            server.CACHED_ENTRIES = {1: {"id": 1, "name": "test.mkv", "size_bytes": 1000}}
            server.READERS_BY_URL["http://mock.test/test.zip"] = mock_reader

        handler = ZipStreamWebHandler.__new__(ZipStreamWebHandler)
        handler.rfile = mock_rfile
        handler.wfile = mock_wfile
        handler.path = "/stream/1/test.mkv"
        handler.headers = {}
        if range_header:
            handler.headers["Range"] = range_header
        
        handler.responses = {}
        headers_sent = {}
        status_code = [None]
        
        def mock_send_response(code, message=None):
            status_code[0] = code

        def mock_send_header(key, val):
            headers_sent[key] = val

        def mock_end_headers():
            pass

        handler.send_response = mock_send_response
        handler.send_header = mock_send_header
        handler.end_headers = mock_end_headers

        with patch("server.StreamPrefetcher") as mock_prefetcher_cls:
            mock_inst = MagicMock()
            mock_inst.stream_chunks.return_value = [b"chunk1", b"chunk2"]
            mock_prefetcher_cls.return_value = mock_inst

            handler.do_GET()

            assert status_code[0] == expected_status
            assert int(headers_sent["Content-Length"]) == expected_len
            assert headers_sent["Accept-Ranges"] == "bytes"
            if expected_cr:
                assert headers_sent["Content-Range"] == expected_cr
            else:
                assert "Content-Range" not in headers_sent


def test_memory_leak_stress():
    """Stress test creating and destroying multiple prefetchers and streams to verify zero memory leaks."""
    payload = b"M" * (1024 * 1024)  # 1 MB
    mock_pool = MockRangePool(payload)

    # Warm-up run to stabilize interpreter allocations
    warmup = StreamPrefetcher(
        url="http://mock.test/stress.bin",
        start_byte=0,
        end_byte=len(payload) - 1,
        pool=mock_pool
    )
    warmup.start()
    for _ in warmup.stream_chunks():
        break
    warmup.close()
    del warmup
    gc.collect()

    initial_threads = threading.active_count()
    prefetchers = []

    for _ in range(50):
        prefetcher = StreamPrefetcher(
            url="http://mock.test/stress.bin",
            start_byte=0,
            end_byte=len(payload) - 1,
            pool=mock_pool
        )
        prefetcher.BLOCK_SIZE = 64 * 1024
        prefetcher.SOCKET_SLICE_SIZE = 16 * 1024
        prefetcher.start()
        
        # Partially read stream then terminate
        count = 0
        for chunk in prefetcher.stream_chunks():
            count += 1
            if count > 2:
                prefetcher.close()
                break
        prefetchers.append(prefetcher)

    # Verify all threads terminate
    for p in prefetchers:
        p.close()
        if p.worker_thread:
            p.worker_thread.join(timeout=0.5)
            assert not p.worker_thread.is_alive()
        assert p.queue.empty()

    del prefetchers
    gc.collect()

    # Active threads should return to baseline
    assert threading.active_count() <= initial_threads + 1


def test_remote_zip_parser_and_offset_lookup():
    """Verify RemoteZipReader correctly parses stored entries and calculates data start offsets."""
    import zipfile
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("test_ep1.mkv", b"STREAM_TEST_CONTENT_12345" * 1000)
        zf.writestr("test_ep2.mp4", b"ANOTHER_VIDEO_FILE_DATA_67890" * 500)
        zf.writestr("notes.txt", b"Test note file inside ZIP")
    zip_bytes = zip_buffer.getvalue()

    from tests.test_zip64 import MockZipRangePool
    mock_pool = MockZipRangePool(zip_bytes)
    reader = RemoteZipReader(url="http://mock.test/archive.zip", pool=mock_pool)

    assert reader.total_size == len(zip_bytes)
    assert len(reader.entries) == 3

    ep1 = next(e for e in reader.entries if e["name"] == "test_ep1.mkv")
    assert ep1["method_name"] == "STORE"
    assert ep1["size_bytes"] == len(b"STREAM_TEST_CONTENT_12345" * 1000)

    data_offset = reader.get_data_offset(ep1)
    assert data_offset > 0
    actual_slice = zip_bytes[data_offset:data_offset + ep1["size_bytes"]]
    assert actual_slice == b"STREAM_TEST_CONTENT_12345" * 1000


def test_playlist_m3u_endpoint():
    """Verify GET /api/playlist.m3u returns correct playlist content and headers."""
    import urllib.request
    test_port = 8797
    server_address = ("127.0.0.1", test_port)
    httpd = ThreadedZipStreamServer(server_address, ZipStreamWebHandler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    time.sleep(0.1)

    try:
        # Populate CACHED_ENTRIES
        with ARCHIVE_LOCK:
            server.CACHED_ENTRIES = {
                1: {"id": 1, "name": "Show.S01E01.1080p.mkv", "size_bytes": 1000},
                2: {"id": 2, "name": "Show.S01E02.1080p.mkv", "size_bytes": 2000}
            }

        req = urllib.request.Request(f"http://127.0.0.1:{test_port}/api/playlist.m3u")
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            assert "application/x-mpegurl" in resp.headers.get("Content-Type")
            content = resp.read().decode("utf-8")
            assert "#EXTM3U" in content
            assert "Show.S01E01.1080p.mkv" in content
            assert f"http://127.0.0.1:{test_port}/stream/1/Show.S01E01.1080p.mkv" in content
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_api_config_get_and_post():
    """Verify GET and POST /api/config runtime settings update."""
    import urllib.request
    test_port = 8798
    server_address = ("127.0.0.1", test_port)
    httpd = ThreadedZipStreamServer(server_address, ZipStreamWebHandler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    time.sleep(0.1)

    try:
        # 1. GET /api/config
        req = urllib.request.Request(f"http://127.0.0.1:{test_port}/api/config")
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["status"] == "ok"
            assert "streaming" in data["config"]

        # 2. POST /api/config
        payload = json.dumps({
            "streaming": {
                "prefetch_buffer_size_mb": 5120,
                "slice_size_kb": 256,
                "chunk_timeout_seconds": 45
            }
        }).encode("utf-8")
        post_req = urllib.request.Request(
            f"http://127.0.0.1:{test_port}/api/config",
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(post_req) as resp:
            assert resp.status == 200
            post_data = json.loads(resp.read().decode("utf-8"))
            assert post_data["status"] == "ok"
            assert post_data["config"]["streaming"]["prefetch_buffer_size_mb"] == 5120
            assert post_data["config"]["streaming"]["slice_size_kb"] == 256
            assert post_data["config"]["streaming"]["chunk_timeout_seconds"] == 45
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_adaptive_chunk_sizing_logic():
    """Verify calculate_adaptive_chunk_size selects optimal chunk sizes."""
    # Subtitles & text -> 1MB
    assert calculate_adaptive_chunk_size(media_filename="subs.srt") == 1024 * 1024
    assert calculate_adaptive_chunk_size(media_filename="subs.vtt") == 1024 * 1024
    assert calculate_adaptive_chunk_size(media_filename="track.ass") == 1024 * 1024

    # Audio -> 1MB
    assert calculate_adaptive_chunk_size(media_filename="audio.flac") == 1024 * 1024
    assert calculate_adaptive_chunk_size(media_filename="music.mp3") == 1024 * 1024

    # Bitrate based
    assert calculate_adaptive_chunk_size(stream_bitrate_bps=50_000_000) == 8 * 1024 * 1024  # 50 Mbps (4K REMUX)
    assert calculate_adaptive_chunk_size(stream_bitrate_bps=20_000_000) == 4 * 1024 * 1024  # 20 Mbps (4K high)
    assert calculate_adaptive_chunk_size(stream_bitrate_bps=8_000_000) == 2 * 1024 * 1024   # 8 Mbps (1080p)
    assert calculate_adaptive_chunk_size(stream_bitrate_bps=2_000_000) == 1024 * 1024       # 2 Mbps (audio/SD)

    # File size based fallback
    assert calculate_adaptive_chunk_size(file_size_bytes=10 * 1024 * 1024 * 1024) == 8 * 1024 * 1024  # 10GB
    assert calculate_adaptive_chunk_size(file_size_bytes=2 * 1024 * 1024 * 1024) == 4 * 1024 * 1024   # 2GB
    assert calculate_adaptive_chunk_size(file_size_bytes=500 * 1024 * 1024) == 2 * 1024 * 1024        # 500MB
    assert calculate_adaptive_chunk_size(file_size_bytes=10 * 1024 * 1024) == 1024 * 1024             # 10MB


def test_metrics_tracker_and_stats():
    """Verify MetricsTracker throughput calculation, active streams count, and helper exports."""
    tracker = MetricsTracker(window_seconds=1.0)
    tracker.reset()

    tracker.register_stream_start()
    assert tracker.get_stats()["active_streams_count"] == 1

    tracker.record_bytes(1024 * 1024)  # 1MB
    stats = tracker.get_stats()
    assert stats["total_bytes_served"] == 1024 * 1024
    assert stats["total_mbytes_served"] == 1.0
    assert stats["current_bandwidth_mbps"] > 0

    tracker.register_stream_end()
    assert tracker.get_stats()["active_streams_count"] == 0


def test_stream_prefetcher_cleanup_hooks_and_context_manager():
    """Verify cleanup hooks and context manager lifecycle execute completely."""
    payload = b"H" * (2 * 1024 * 1024)
    mock_pool = MockRangePool(payload)
    hook_called = [False]

    def on_cleanup():
        hook_called[0] = True

    with StreamPrefetcher(
        url="http://mock.test/hook.mkv",
        start_byte=0,
        end_byte=len(payload) - 1,
        pool=mock_pool,
        filename="hook.mkv"
    ) as prefetcher:
        prefetcher.add_cleanup_hook(on_cleanup)
        # Read a chunk
        for chunk in prefetcher.stream_chunks():
            assert len(chunk) > 0
            break

    assert hook_called[0] is True
    assert prefetcher._closed is True
    assert prefetcher.queue.empty()


def test_api_stats_endpoint():
    """Verify /api/stats endpoint returns real-time metrics."""
    import urllib.request
    test_port = 8792
    server_address = ("127.0.0.1", test_port)
    httpd = ThreadedZipStreamServer(server_address, ZipStreamWebHandler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    time.sleep(0.2)

    try:
        req = urllib.request.Request(f"http://127.0.0.1:{test_port}/api/stats")
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["status"] == "ok"
            assert "stats" in data
            assert "active_streams_count" in data["stats"]
            assert "current_bandwidth_mbps" in data["stats"]
            assert "total_bytes_served" in data["stats"]
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_api_logs_endpoint_and_ring_buffer():
    """Verify in-memory LogBuffer ring buffer, logging tags/emojis, and /api/logs endpoint."""
    from engine import LogBuffer, LOG_BUFFER, log_event, format_bytes_human
    import urllib.request
    
    # Unit test LogBuffer operations
    buf = LogBuffer(capacity=5)
    e1 = buf.append("SCAN START", "🔍", "Testing 1", level="info")
    e2 = buf.append("ARCHIVE SIZE", "🎯", "Testing 2", level="info")
    e3 = buf.append("TAIL FETCH", "⚡", "Testing 3", level="info")
    
    assert len(buf.get_logs()) == 3
    assert buf.get_logs(since_id=e1["id"]) == [e2, e3]
    
    # Capacity wrapping
    buf.append("CENTRAL DIR", "📂", "Testing 4")
    buf.append("SCAN STATS", "📊", "Testing 5")
    buf.append("STREAM START", "🎬", "Testing 6")
    logs = buf.get_logs()
    assert len(logs) == 5
    assert logs[0]["message"] == "Testing 2"  # Testing 1 evicted

    # Server integration test for /api/logs?since=...
    log_event("STREAM START", "🎬", "Integration test log event", level="info")
    test_port = 8794
    server_address = ("127.0.0.1", test_port)
    httpd = ThreadedZipStreamServer(server_address, ZipStreamWebHandler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    time.sleep(0.2)

    try:
        req = urllib.request.Request(f"http://127.0.0.1:{test_port}/api/logs")
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["status"] == "ok"
            assert "logs" in data
            assert isinstance(data["logs"], list)
            assert len(data["logs"]) > 0

            latest_id = data["logs"][-1]["id"]
            req_since = urllib.request.Request(f"http://127.0.0.1:{test_port}/api/logs?since={latest_id}")
            with urllib.request.urlopen(req_since, timeout=5) as resp_since:
                assert resp_since.status == 200
                data_since = json.loads(resp_since.read().decode("utf-8"))
                assert data_since["status"] == "ok"
                assert len(data_since["logs"]) == 0
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_api_ping_endpoint_and_auto_attach():
    """Verify /api/ping endpoint returns correct signature and handshake works."""
    import urllib.request
    import os
    from src.zipstream.server import check_running_instance
    test_port = 8793
    server_address = ("127.0.0.1", test_port)
    httpd = ThreadedZipStreamServer(server_address, ZipStreamWebHandler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    time.sleep(0.2)

    try:
        # Test direct GET /api/ping
        req = urllib.request.Request(f"http://127.0.0.1:{test_port}/api/ping")
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["status"] == "ok"
            assert data["app"] == "zipstream-hub"
            assert data["version"] == "1.0.0"
            assert data["pid"] == os.getpid()
            assert "uptime" in data
            assert data["port"] == test_port

        # Test check_running_instance helper
        res = check_running_instance(test_port)
        assert res is not None
        assert res["app"] == "zipstream-hub"
        assert res["pid"] == os.getpid()
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_server_port_helpers_and_auto_port():
    """Verify dynamic port hunting, availability checks, active port persistence, and CLI arg parsing."""
    from src.zipstream.server import (
        is_port_available,
        find_free_port,
        save_active_port,
        get_active_port,
        remove_active_port_file,
        parse_args
    )
    import socket

    # Test port available check on open socket vs free port
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    bound_port = s.getsockname()[1]

    assert not is_port_available(bound_port)
    next_free = find_free_port(start_port=bound_port)
    assert next_free != bound_port
    assert is_port_available(next_free)
    s.close()

    # Test active port file persistence
    save_active_port(9999)
    assert get_active_port(fallback=8787) == 9999
    remove_active_port_file()
    assert get_active_port(fallback=8787) == 8787

    # Test CLI argument parsing
    with patch("sys.argv", ["server.py", "--port", "8990", "--auto-port"]):
        args = parse_args()
        assert args.port == 8990
        assert args.auto_port is True

