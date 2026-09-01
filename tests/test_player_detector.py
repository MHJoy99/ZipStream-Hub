"""
Unit tests for media player detector and dynamic player endpoints.
"""

import os
import sys
import json
import urllib.request
import threading
import time
import pytest

# Ensure root directory is on python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from player_detector import get_installed_players, launch_stream, PLAYER_DEFINITIONS
from server import ThreadedZipStreamServer, ZipStreamWebHandler


def test_player_detector_detection():
    players = get_installed_players()
    assert isinstance(players, dict)
    assert "browser" in players
    assert players["browser"]["available"] is True
    assert players["browser"]["key"] == "browser"

    # Verify recognized players format
    for k, v in players.items():
        assert "name" in v
        assert "path" in v
        assert "available" in v


def test_player_detector_browser_fallback_launch():
    res = launch_stream("browser", "http://127.0.0.1:8787/stream/1/test.mkv")
    assert res["success"] is True
    assert res["key"] == "browser"


def test_api_players_and_play_endpoints():
    test_port = 8882
    server = ThreadedZipStreamServer(("127.0.0.1", test_port), ZipStreamWebHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    time.sleep(0.2)

    try:
        # 1. Test GET /api/players
        req = urllib.request.Request(f"http://127.0.0.1:{test_port}/api/players")
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["status"] == "ok"
            assert "players" in data
            assert len(data["players"]) >= 1
            assert any(p["key"] == "browser" for p in data["players"])

        # 2. Test POST /api/play with browser
        payload = json.dumps({"url": f"http://127.0.0.1:{test_port}/stream/0/test.mp4", "player": "browser"}).encode("utf-8")
        post_req = urllib.request.Request(
            f"http://127.0.0.1:{test_port}/api/play",
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(post_req) as resp:
            assert resp.status == 200
            res_data = json.loads(resp.read().decode("utf-8"))
            assert res_data["success"] is True
            assert res_data["key"] == "browser"

    finally:
        server.shutdown()
        server.server_close()
