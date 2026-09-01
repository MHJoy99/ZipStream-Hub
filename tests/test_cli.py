"""
Unit tests for ZipStreamHub CLI & Interactive Terminal Suite (cli.py).
Tests both interactive command execution and non-interactive command line modes.
"""

import io
import os
import sys
import zipfile
import pytest
from unittest.mock import MagicMock, patch

# Ensure repo root is at the very beginning of sys.path to avoid picking up virtualenv's cli.py
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)
if "cli" in sys.modules and getattr(sys.modules["cli"], "__file__", "") != os.path.join(repo_root, "cli.py"):
    del sys.modules["cli"]

import cli
from cli import (
    format_bytes,
    format_duration,
    export_m3u_playlist,
    export_strm_bundle,
    print_archive_overview,
    print_video_table,
    print_active_stats,
    play_item,
    build_arg_parser,
    main,
    CLIStreamingServer,
)


class DummyReader:
    def __init__(self):
        self.url = "http://example.com/test.zip"
        self.total_size = 3500000000
        self.entries = [
            {
                "id": 1,
                "name": "Breaking.Bad.S01E01.1080p.mkv",
                "size_bytes": 1500000000,
                "comp_size_bytes": 1500000000,
                "method": 0,
                "method_name": "STORE",
                "offset": 0,
            },
            {
                "id": 2,
                "name": "Breaking.Bad.S01E02.1080p.mp4",
                "size_bytes": 2000000000,
                "comp_size_bytes": 2000000000,
                "method": 8,
                "method_name": "DEFLATE",
                "offset": 1000,
            },
            {
                "id": 3,
                "name": "Breaking.Bad.S01E01.en.srt",
                "size_bytes": 45000,
                "comp_size_bytes": 15000,
                "method": 8,
                "method_name": "DEFLATE",
                "offset": 2000,
            }
        ]

    def get_data_offset(self, entry):
        return 100


def test_format_bytes():
    assert format_bytes(500) == "500 B"
    assert format_bytes(2048) == "2.0 KB"
    assert format_bytes(5 * 1024 * 1024) == "5.0 MB"
    assert format_bytes(3 * 1024 * 1024 * 1024) == "3.00 GB"
    assert format_bytes(2 * 1024 * 1024 * 1024 * 1024) == "2.00 TB"


def test_format_duration():
    assert format_duration(None) == "--:--"
    assert format_duration(0) == "--:--"
    assert format_duration(65) == "01:05"
    assert format_duration(3665) == "01:01:05"


def test_export_m3u_playlist(tmp_path):
    reader = DummyReader()
    out_file = str(tmp_path / "test_playlist.m3u")
    res = export_m3u_playlist(reader, out_file, "http://127.0.0.1:8787")
    assert res == out_file
    assert os.path.exists(out_file)

    with open(out_file, "r", encoding="utf-8") as f:
        content = f.read()

    assert "#EXTM3U" in content
    assert "tvg-name=\"Breaking.Bad.S01E01.1080p.mkv\"" in content
    assert "http://127.0.0.1:8787/stream/1/Breaking.Bad.S01E01.1080p.mkv" in content
    assert "http://127.0.0.1:8787/stream/2/Breaking.Bad.S01E02.1080p.mp4" in content
    assert ".srt" not in content


def test_export_strm_bundle(tmp_path):
    reader = DummyReader()
    out_file = str(tmp_path / "test_strm.zip")
    res = export_strm_bundle(reader, out_file, "http://127.0.0.1:8787")
    assert res == out_file
    assert os.path.exists(out_file)

    with zipfile.ZipFile(out_file, "r") as zf:
        names = zf.namelist()
        assert any("S01E01.strm" in n for n in names)
        assert any("S01E02.strm" in n for n in names)
        # Verify .strm content
        strm_1 = [n for n in names if "S01E01" in n][0]
        strm_data = zf.read(strm_1).decode("utf-8")
        assert "http://127.0.0.1:8787/stream/1/Breaking.Bad.S01E01.1080p.mkv" in strm_data


def test_print_archive_overview_and_table(capsys):
    reader = DummyReader()
    print_archive_overview(reader)
    captured = capsys.readouterr().out
    assert "ARCHIVE OVERVIEW" in captured
    assert "STORE" in captured
    assert "DEFLATE" in captured

    inspect_cache = {}
    print_video_table(reader, inspect_cache)
    captured_table = capsys.readouterr().out
    assert "RESOLUTION" in captured_table
    assert "Breaking.Bad.S01E01" in captured_table


def test_print_active_stats(capsys):
    print_active_stats()
    captured = capsys.readouterr().out
    assert "STREAMING THROUGHPUT STATS" in captured
    assert "Current Bandwidth" in captured


def test_play_item_launch(monkeypatch):
    reader = DummyReader()
    server_mgr = MagicMock()
    server_mgr.port = 8787

    with patch("player_detector.launch_stream") as mock_launch:
        mock_launch.return_value = {"success": True, "player": "VLC", "key": "vlc"}
        success = play_item(reader, 1, player_target="vlc", server_mgr=server_mgr, port=8787)
        assert success is True
        mock_launch.assert_called_once()
        args, kwargs = mock_launch.call_args
        assert args[0] == "vlc"
        assert "http://127.0.0.1:8787/stream/1/" in args[1]


def test_cli_arg_parser():
    parser = build_arg_parser()
    args = parser.parse_args(["http://test.com/archive.zip", "--play", "1", "--player", "vlc", "--port", "9090"])
    assert args.url == "http://test.com/archive.zip"
    assert args.play_id == 1
    assert args.player == "vlc"
    assert args.port == 9090

    args2 = parser.parse_args(["http://test.com/archive.zip", "--export-m3u", "my.m3u", "--export-strm", "my.zip"])
    assert args2.export_m3u == "my.m3u"
    assert args2.export_strm == "my.zip"


def test_non_interactive_m3u_and_strm(tmp_path, monkeypatch):
    m3u_out = str(tmp_path / "out.m3u")
    strm_out = str(tmp_path / "out.zip")

    test_args = ["cli.py", "http://example.com/archive.zip", "--export-m3u", m3u_out, "--export-strm", strm_out]
    monkeypatch.setattr(sys, "argv", test_args)

    with patch("engine.RemoteZipReader", return_value=DummyReader()):
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 0

    assert os.path.exists(m3u_out)
    assert os.path.exists(strm_out)


def test_non_interactive_list(monkeypatch, capsys):
    test_args = ["cli.py", "http://example.com/archive.zip", "--list"]
    monkeypatch.setattr(sys, "argv", test_args)

    with patch("engine.RemoteZipReader", return_value=DummyReader()):
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 0

    captured = capsys.readouterr().out
    assert "ARCHIVE OVERVIEW" in captured
    assert "FILENAME" in captured
