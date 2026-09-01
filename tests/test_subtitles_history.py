import os
import io
import tempfile
import urllib.parse
from unittest.mock import MagicMock
import pytest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from subtitle_parser import (
    match_subtitles_for_video,
    package_subtitles_for_video,
    pair_archive_subtitles,
    srt_to_vtt,
    ass_to_vtt,
    convert_to_vtt,
    is_subtitle_file,
    is_video_file,
    normalize_language_code,
    get_language_display_name,
    parse_scene_release,
    sanitize_vtt_cue_text,
    SubtitleTrack,
    SubtitlePackage,
    _extract_episode_number,
    _detect_language,
)
from history import (
    HistoryManager,
    add_history,
    get_history,
    toggle_favorite,
    delete_history,
)


# ==========================================
# Subtitle Matching & Detection Tests
# ==========================================

def test_subtitle_and_video_extension_checks():
    assert is_subtitle_file("sub.srt") is True
    assert is_subtitle_file("sub.vtt") is True
    assert is_subtitle_file("sub.ass") is True
    assert is_subtitle_file("sub.ssa") is True
    assert is_subtitle_file("sub.mp4") is False

    assert is_video_file("video.mkv") is True
    assert is_video_file("video.mp4") is True
    assert is_video_file("video.webm") is True
    assert is_video_file("video.srt") is False


def test_episode_number_extraction():
    assert _extract_episode_number("Show.S01E05.1080p.mkv") == 5
    assert _extract_episode_number("Show_s2e12.mp4") == 12
    assert _extract_episode_number("Anime - 08.mkv") == 8
    assert _extract_episode_number("Subs/01.srt") == 1
    assert _extract_episode_number("Episode 04.ass") == 4
    assert _extract_episode_number("Movie (2024).mkv") is None


def test_language_detection():
    lang, label = _detect_language("Show.S01E01.en.srt")
    assert lang == "en"
    assert "English" in label

    lang, label = _detect_language("Show.S01E01.ja.ass")
    assert lang == "ja"
    assert "Japanese" in label

    lang, label = _detect_language("Subs/Chinese/01.srt")
    assert "Chinese" in label


def test_iso_language_code_normalization():
    # ISO 639-2 to 639-1 mappings
    assert normalize_language_code("eng") == "en"
    assert normalize_language_code("spa") == "es"
    assert normalize_language_code("fre") == "fr"
    assert normalize_language_code("fra") == "fr"
    assert normalize_language_code("jpn") == "ja"
    assert normalize_language_code("chi") == "zh"
    assert normalize_language_code("zho") == "zh"
    assert normalize_language_code("deu") == "de"
    assert normalize_language_code("ger") == "de"
    assert normalize_language_code("ita") == "it"
    assert normalize_language_code("por") == "pt"
    assert normalize_language_code("rus") == "ru"
    assert normalize_language_code("kor") == "ko"
    assert normalize_language_code("unknown_xyz") == "und"

    # Display name lookup
    assert get_language_display_name("eng") == "English"
    assert get_language_display_name("spa") == "Spanish"
    assert get_language_display_name("fre") == "French"
    assert get_language_display_name("jpn") == "Japanese"
    assert get_language_display_name("chi") == "Chinese"


def test_complex_scene_release_parsing_and_nlp_matching():
    video_entry = {
        "id": 1,
        "name": "[Group] Show Name - S01E05 - 1080p [Dual-Audio] [A1B2C3D4].mkv",
        "size_bytes": 1200000000,
    }
    archive_entries = [
        video_entry,
        {"id": 2, "name": "Show.Name.1x05.en.forced.srt", "size_bytes": 15000},
        {"id": 3, "name": "Subs/05_English.ass", "size_bytes": 45000},
        {"id": 4, "name": "Season 1/Ep 5.vtt", "size_bytes": 20000},
        {"id": 5, "name": "Show.Name.1x06.en.srt", "size_bytes": 16000},  # Episode 6 (should NOT match)
        {"id": 6, "name": "Subs/06_Japanese.ass", "size_bytes": 40000},   # Episode 6 (should NOT match)
    ]

    matched = match_subtitles_for_video(video_entry, archive_entries)
    matched_ids = [t.id for t in matched]
    
    assert 2 in matched_ids
    assert 3 in matched_ids
    assert 4 in matched_ids
    assert 5 not in matched_ids
    assert 6 not in matched_ids

    # Check track flags & languages
    track_2 = next(t for t in matched if t.id == 2)
    assert track_2.language == "en"
    assert track_2.is_forced is True
    assert "Forced" in track_2.label

    track_3 = next(t for t in matched if t.id == 3)
    assert track_3.language == "en"
    assert track_3.is_forced is False


def test_subtitle_package_and_multi_track():
    video_entry = {"id": 10, "name": "Movie.2024.1080p.mkv", "size_bytes": 2000000000}
    entries = [
        video_entry,
        {"id": 11, "name": "Movie.2024.eng.srt", "size_bytes": 50000},
        {"id": 12, "name": "Movie.2024.spa.srt", "size_bytes": 48000},
        {"id": 13, "name": "Movie.2024.fre.srt", "size_bytes": 49000},
        {"id": 14, "name": "Movie.2024.jpn.srt", "size_bytes": 42000},
        {"id": 15, "name": "Movie.2024.chi.srt", "size_bytes": 41000},
    ]

    pkg = package_subtitles_for_video(video_entry, entries)
    assert isinstance(pkg, SubtitlePackage)
    assert pkg.video_id == 10
    assert len(pkg.tracks) == 5

    pkg_dict = pkg.to_dict()
    assert pkg_dict["track_count"] == 5

    # Test track retrieval by language
    en_track = pkg.get_track_by_language("en")
    assert en_track is not None
    assert en_track.id == 11
    assert en_track.language == "en"

    es_track = pkg.get_track_by_language("spa")
    assert es_track is not None
    assert es_track.id == 12
    assert es_track.language == "es"

    fr_track = pkg.get_track_by_language("fra")
    assert fr_track is not None
    assert fr_track.id == 13
    assert fr_track.language == "fr"

    ja_track = pkg.get_track_by_language("jpn")
    assert ja_track is not None
    assert ja_track.id == 14
    assert ja_track.language == "ja"

    zh_track = pkg.get_track_by_language("zho")
    assert zh_track is not None
    assert zh_track.id == 15
    assert zh_track.language == "zh"


def test_vtt_cue_sanitization():
    # 1. Unsafe script tags & ASS override tags
    dirty_text = "<script>alert('xss')</script>{\\pos(192,200)}{\\c&H0000FF&}Hello <b>World</b>!\\NSecond Line"
    clean = sanitize_vtt_cue_text(dirty_text)
    assert "<script>" not in clean
    assert "{\\pos" not in clean
    assert "{\\c&H" not in clean
    assert "<b>World</b>" in clean
    assert "Hello" in clean
    assert "Second Line" in clean

    # 2. SRT with font tags and dirty cues converted to clean VTT
    dirty_srt = """1
00:00:01,000 --> 00:00:04,000
<font color="#ff0000"><b>Red Text</b></font> &amp; More
<script>malicious()</script>
"""
    vtt_res = srt_to_vtt(dirty_srt)
    assert "<font" not in vtt_res
    assert "<script" not in vtt_res
    assert "<b>Red Text</b> & More" in vtt_res


def test_subtitle_matching_multi_episode():
    entries = [
        {"id": 1, "name": "Breaking.Bad.S01E01.mkv", "size_bytes": 1000000000},
        {"id": 2, "name": "Breaking.Bad.S01E02.mkv", "size_bytes": 1000000000},
        {"id": 3, "name": "Breaking.Bad.S01E01.en.srt", "size_bytes": 45000},
        {"id": 4, "name": "Breaking.Bad.S01E01.es.srt", "size_bytes": 44000},
        {"id": 5, "name": "Breaking.Bad.S01E02.en.srt", "size_bytes": 46000},
        {"id": 6, "name": "OtherFile.txt", "size_bytes": 120},
    ]

    ep1_tracks = match_subtitles_for_video(entries[0], entries)
    assert len(ep1_tracks) == 2
    assert ep1_tracks[0].id == 3
    assert ep1_tracks[0].language == "en"
    assert ep1_tracks[1].id == 4
    assert ep1_tracks[1].language == "es"

    ep2_tracks = match_subtitles_for_video(entries[1], entries)
    assert len(ep2_tracks) == 1
    assert ep2_tracks[0].id == 5

    paired = pair_archive_subtitles(entries)
    assert 1 in paired
    assert 2 in paired
    assert len(paired[1]) == 2
    assert len(paired[2]) == 1


def test_subtitle_matching_folder_hierarchy():
    entries = [
        {"id": 1, "name": "Frieren - S01E05.mkv", "size_bytes": 800000000},
        {"id": 2, "name": "Subs/English/05.ass", "size_bytes": 55000},
        {"id": 3, "name": "Subs/Japanese/05.ass", "size_bytes": 50000},
        {"id": 4, "name": "Subs/English/06.ass", "size_bytes": 56000},
    ]

    matched = match_subtitles_for_video(entries[0], entries)
    assert len(matched) == 2
    matched_ids = [t.id for t in matched]
    assert 2 in matched_ids
    assert 3 in matched_ids
    assert 4 not in matched_ids


# ==========================================
# WebVTT Conversion Tests
# ==========================================

def test_srt_to_vtt_conversion():
    srt_input = """1
00:01:20,500 --> 00:01:23,100
Hello, world!
This is a test subtitle.

2
00:01:24,000 --> 00:01:27,500
Second subtitle cue.
"""
    vtt_output = srt_to_vtt(srt_input)
    assert vtt_output.startswith("WEBVTT")
    assert "00:01:20.500 --> 00:01:23.100" in vtt_output
    assert "Hello, world!" in vtt_output
    assert "00:01:24.000 --> 00:01:27.500" in vtt_output
    assert "Second subtitle cue." in vtt_output


def test_ass_to_vtt_conversion():
    ass_input = """[Script Info]
Title: Sample ASS
ScriptType: v4.00+

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,2,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:01:05.12,0:01:08.50,Default,,0,0,0,,{\\pos(192,200)}Hello from \\NASS Subtitle!
Dialogue: 0,0:01:10.00,0:01:12.30,Default,,0,0,0,,{\\b1}Bold Line{\\b0}
"""
    vtt_output = ass_to_vtt(ass_input)
    assert vtt_output.startswith("WEBVTT")
    assert "00:01:05.120 --> 00:01:08.500" in vtt_output
    assert "Hello from\nASS Subtitle!" in vtt_output
    assert "{\\pos" not in vtt_output
    assert "00:01:10.000 --> 00:01:12.300" in vtt_output
    assert "Bold Line" in vtt_output


def test_convert_to_vtt_dispatcher():
    srt_raw = "1\n00:00:01,000 --> 00:00:02,000\nTesting SRT"
    vtt_res = convert_to_vtt(srt_raw, "track.srt")
    assert "00:00:01.000 --> 00:00:02.000" in vtt_res

    vtt_raw = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nAlready VTT"
    assert convert_to_vtt(vtt_raw, ".vtt").startswith("WEBVTT")


# ==========================================
# History & Favorites Storage Tests
# ==========================================

def test_history_manager_crud():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_history.db")
        manager = HistoryManager(db_path)

        # 1. Add history
        url1 = "https://example.com/archive1.zip"
        res1 = manager.add_history(url=url1, title="Archive One", size_bytes=1073741824, file_count=5)
        assert res1["url"] == url1
        assert res1["title"] == "Archive One"
        assert res1["size_gb"] == 1.0
        assert res1["file_count"] == 5
        assert res1["is_favorite"] is False

        # 2. Get history
        hist = manager.get_history()
        assert len(hist) == 1
        assert hist[0]["url"] == url1

        # 3. Add second archive
        url2 = "https://example.com/archive2.zip"
        manager.add_history(url=url2, title="Archive Two", size_bytes=2147483648, file_count=10)

        hist = manager.get_history(limit=10)
        assert len(hist) == 2
        # Most recent first
        assert hist[0]["url"] == url2

        # 4. Toggle favorite
        is_fav = manager.toggle_favorite(url1)
        assert is_fav is True
        favs = manager.get_history(favorites_only=True)
        assert len(favs) == 1
        assert favs[0]["url"] == url1

        # Untoggle favorite
        is_fav_now = manager.toggle_favorite(url1)
        assert is_fav_now is False
        assert len(manager.get_history(favorites_only=True)) == 0

        # 5. Delete entry
        deleted = manager.delete_history(url2)
        assert deleted is True
        assert len(manager.get_history()) == 1

        # 6. Clear history
        manager.toggle_favorite(url1)
        manager.add_history("https://example.com/archive3.zip", "Archive 3")
        assert len(manager.get_history()) == 2
        
        # Clear non-favorites
        manager.clear_history(keep_favorites=True)
        remaining = manager.get_history()
        assert len(remaining) == 1
        assert remaining[0]["url"] == url1

        # Clear all
        manager.clear_history(keep_favorites=False)
        assert len(manager.get_history()) == 0


def test_module_level_history_functions():
    # Test fallback module methods
    url = "https://test.local/temp_test.zip"
    entry = add_history(url, title="Test", size_bytes=5000, file_count=2)
    assert entry["url"] == url

    hist = get_history(limit=5)
    assert any(h["url"] == url for h in hist)

    fav_state = toggle_favorite(url)
    assert isinstance(fav_state, bool)

    del_state = delete_history(url)
    assert del_state is True


# ==========================================
# Server Endpoints Tests (Playlist, Subtitle, History)
# ==========================================

from server import ThreadedZipStreamServer, ZipStreamWebHandler, ARCHIVE_LOCK
import server
import json
import urllib.request
import threading
import time


def test_server_history_and_subtitle_and_playlist_endpoints():
    test_port = 8884
    httpd = ThreadedZipStreamServer(("127.0.0.1", test_port), ZipStreamWebHandler)
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()
    time.sleep(0.2)

    try:
        base = f"http://127.0.0.1:{test_port}"

        # 1. Setup mock active reader in server
        mock_reader = MagicMock()
        mock_reader.url = "http://example.com/anime.zip"
        mock_reader.total_size = 10000000
        mock_reader.entries = [
            {"id": 1, "name": "Episode 01.mkv", "size_bytes": 5000000},
            {"id": 2, "name": "Episode 01.srt", "size_bytes": 100, "method": 0, "comp_size_bytes": 100},
            {"id": 3, "name": "Episode 02.mp4", "size_bytes": 4500000}
        ]
        mock_reader.get_data_offset.return_value = 1000
        srt_sample = "1\n00:00:01,000 --> 00:00:04,000\nHello from ZIP stream!\n"
        mock_reader.read_entry_bytes.return_value = srt_sample.encode("utf-8")

        with ARCHIVE_LOCK:
            server.CURRENT_READER = mock_reader
            server.CACHED_ENTRIES = {e["id"]: e for e in mock_reader.entries}
            server.READERS_BY_URL[mock_reader.url] = mock_reader

        # 2. Test GET /api/playlist.m3u
        req = urllib.request.Request(f"{base}/api/playlist.m3u")
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200
            assert "application/x-mpegurl" in resp.headers.get("Content-Type", "")
            m3u_text = resp.read().decode("utf-8")
            assert "#EXTM3U" in m3u_text
            assert 'tvg-name="Episode 01.mkv"' in m3u_text
            assert 'group-title="ZipStream Hub"' in m3u_text
            assert f"{base}/stream/1/Episode%2001.mkv" in m3u_text
            assert 'tvg-name="Episode 02.mp4"' in m3u_text
            # SRT file should not be included as video track
            assert "Episode 01.srt" not in m3u_text

        # 3. Test GET /api/subtitle (auto VTT conversion)
        req_sub = urllib.request.Request(f"{base}/api/subtitle?id=2")
        with urllib.request.urlopen(req_sub, timeout=5) as resp:
            assert resp.status == 200
            assert "text/vtt" in resp.headers.get("Content-Type", "")
            vtt_content = resp.read().decode("utf-8")
            assert vtt_content.startswith("WEBVTT")
            assert "00:00:01.000 --> 00:00:04.000" in vtt_content
            assert "Hello from ZIP stream!" in vtt_content

        # 4. Test GET /api/history
        req_hist = urllib.request.Request(f"{base}/api/history")
        with urllib.request.urlopen(req_hist, timeout=5) as resp:
            assert resp.status == 200
            hist_json = json.loads(resp.read().decode("utf-8"))
            assert hist_json["status"] == "ok"
            assert isinstance(hist_json["history"], list)

        # 5. Test POST /api/history/favorite
        fav_url = "https://example.com/favorite_test.zip"
        post_fav = urllib.request.Request(
            f"{base}/api/history/favorite",
            data=json.dumps({"url": fav_url}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(post_fav, timeout=5) as resp:
            assert resp.status == 200
            fav_data = json.loads(resp.read().decode("utf-8"))
            assert fav_data["status"] == "ok"
            assert fav_data["is_favorite"] is True

        # 6. Test DELETE /api/history
        del_req = urllib.request.Request(
            f"{base}/api/history?url={urllib.parse.quote(fav_url)}",
            method="DELETE"
        )
        with urllib.request.urlopen(del_req, timeout=5) as resp:
            assert resp.status == 200
            del_data = json.loads(resp.read().decode("utf-8"))
            assert del_data["status"] == "ok"
            assert del_data["deleted"] is True

        # 7. Test GET /api/strm.zip
        req_strm = urllib.request.Request(f"{base}/api/strm.zip")
        with urllib.request.urlopen(req_strm, timeout=5) as resp:
            assert resp.status == 200
            assert "application/zip" in resp.headers.get("Content-Type", "")
            zip_bytes = resp.read()
            assert len(zip_bytes) > 0
            import zipfile
            import io
            with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
                namelist = zf.namelist()
                assert len(namelist) >= 2
                assert any(name.endswith(".strm") for name in namelist)

        # 8. Test GET /api/media_inspect
        mock_reader.get_data_offset.return_value = 0
        mock_reader._fetch_range.return_value = b"\x1a\x45\xdf\xa3\x9f\x42\x86\x81\x01\x42\xf7\x81\x01\x42\xf2\x81\x04\x42\xf3\x81\x08\x42\x82\x88matroska"
        req_inspect = urllib.request.Request(f"{base}/api/media_inspect?id=1")
        with urllib.request.urlopen(req_inspect, timeout=5) as resp:
            assert resp.status == 200
            assert "application/json" in resp.headers.get("Content-Type", "")
            insp_data = json.loads(resp.read().decode("utf-8"))
            assert insp_data["status"] == "ok"
            assert "media_info" in insp_data

    finally:
        httpd.shutdown()
        httpd.server_close()
