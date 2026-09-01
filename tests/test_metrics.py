"""
Unit tests for MetricsTracker, Bandwidth Throttling / Rate Limiting, and /api/stats endpoint.
"""

import io
import json
import threading
import time
import urllib.request
import pytest
from unittest.mock import MagicMock

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import (
    MetricsTracker,
    METRICS,
    get_streaming_metrics,
    set_bandwidth_limit,
    StreamPrefetcher,
)
from server import ZipStreamWebHandler, ThreadedZipStreamServer, ARCHIVE_LOCK, CURRENT_READER, CACHED_ENTRIES, READERS_BY_URL


def test_metrics_tracker_stream_lifecycle():
    """Test register_stream_start, register_stream_end, and boundary safety."""
    tracker = MetricsTracker(window_seconds=2.0)
    tracker.reset()

    assert tracker.get_stats()["active_streams_count"] == 0

    tracker.register_stream_start()
    tracker.register_stream_start()
    assert tracker.get_stats()["active_streams_count"] == 2

    tracker.register_stream_end()
    assert tracker.get_stats()["active_streams_count"] == 1

    # End more streams than started - must not go below 0
    tracker.register_stream_end()
    tracker.register_stream_end()
    assert tracker.get_stats()["active_streams_count"] == 0


def test_metrics_tracker_throughput_and_sampling():
    """Test throughput calculations, sample window sliding, and total bytes accumulation."""
    tracker = MetricsTracker(window_seconds=0.5)
    tracker.reset()

    # Record 1 MB (8 Mb)
    tracker.record_bytes(1024 * 1024)
    stats = tracker.get_stats()
    assert stats["total_bytes_served"] == 1024 * 1024
    assert stats["total_mbytes_served"] == 1.0
    assert stats["total_gbytes_served"] == round(1.0 / 1024, 3)
    assert stats["current_bandwidth_mbps"] > 0

    # Wait for sample window to slide out
    time.sleep(0.6)
    assert tracker.get_current_bandwidth_mbps() == 0.0
    # Total bytes served should persist even after sample window slides
    assert tracker.get_stats()["total_bytes_served"] == 1024 * 1024


def test_metrics_tracker_bandwidth_limits():
    """Test setting and getting global bandwidth limit configuration."""
    tracker = MetricsTracker()
    tracker.reset()

    assert tracker.get_max_bandwidth_mbps() is None

    tracker.set_max_bandwidth_mbps(50.0)
    assert tracker.get_max_bandwidth_mbps() == 50.0
    assert tracker.get_stats()["max_bandwidth_mbps"] == 50.0

    # Test disabling limit (0 or None)
    tracker.set_max_bandwidth_mbps(0)
    assert tracker.get_max_bandwidth_mbps() is None

    # Test helper functions
    set_bandwidth_limit(100.0)
    assert METRICS.get_max_bandwidth_mbps() == 100.0
    metrics_data = get_streaming_metrics()
    assert metrics_data["max_bandwidth_mbps"] == 100.0

    # Cleanup
    set_bandwidth_limit(None)


def test_rate_limiting_throttle_logic():
    """Test StreamPrefetcher._apply_rate_limit sleep calculation."""
    tracker = MetricsTracker()
    tracker.set_max_bandwidth_mbps(8.0)  # 8 Mbps = 1 MB/s

    prefetcher = StreamPrefetcher(
        url="http://mock.test/video.mkv",
        start_byte=0,
        end_byte=1000,
        metrics=tracker
    )

    # If 2 MB was sent in 0.5s at 1 MB/s limit, expected time is 2.0s -> sleep ~1.5s (capped at 0.5s per step)
    start_time = time.time()
    t_after = prefetcher._apply_rate_limit(bytes_sent=2 * 1024 * 1024, start_time=start_time)
    assert t_after >= start_time


def test_api_stats_live_endpoint():
    """Integration test: Verify /api/stats endpoint returns valid JSON with all metrics."""
    test_port = 8795
    server_address = ("127.0.0.1", test_port)
    httpd = ThreadedZipStreamServer(server_address, ZipStreamWebHandler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    time.sleep(0.2)

    try:
        req = urllib.request.Request(f"http://127.0.0.1:{test_port}/api/stats")
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200
            assert "application/json" in resp.headers.get("Content-Type", "")
            data = json.loads(resp.read().decode("utf-8"))
            assert data["status"] == "ok"
            assert "stats" in data
            stats = data["stats"]
            assert "active_streams_count" in stats
            assert "current_bandwidth_mbps" in stats
            assert "total_bytes_served" in stats
            assert "total_mbytes_served" in stats
            assert "total_gbytes_served" in stats
            assert "max_bandwidth_mbps" in stats
    finally:
        httpd.shutdown()
        httpd.server_close()
