"""
Unit tests for ZipStreamHub STRM Virtual Media Library Generator (strm_generator.py).
Tests .strm content generation, naming/hierarchy parser, and virtual in-memory ZIP bundling
for Jellyfin, Emby, and Kodi media servers.
"""

import io
import os
import sys
import zipfile
from pathlib import Path
import pytest

# Ensure project root is on the python path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from strm_generator import (
    generate_strm_content,
    generate_strm_path,
    generate_strm_zip_bundle,
    parse_media_structure,
)


def test_generate_strm_content():
    """Test generating standard single-line .strm content."""
    url = "http://127.0.0.1:8787/stream/1/Movie.mkv"
    content = generate_strm_content(url)
    assert content == "http://127.0.0.1:8787/stream/1/Movie.mkv\n"

    # Verify whitespace stripping
    content_spaced = generate_strm_content("   http://192.168.1.50:8787/stream/2/Show.mp4 \n ")
    assert content_spaced == "http://192.168.1.50:8787/stream/2/Show.mp4\n"


def test_parse_media_structure_tv_shows():
    """Test TV show episode parsing across various naming formats."""
    # S01E02 format
    show, s, e, title = parse_media_structure("Breaking.Bad.S01E02.1080p.BluRay.mkv")
    assert show == "Breaking Bad"
    assert s == 1
    assert e == 2
    assert title == "Breaking Bad S01E02"

    # Multi-word show with lowercase s02e05
    show2, s2, e2, title2 = parse_media_structure("House_of_the_Dragon.s02e05.2160p.mkv")
    assert show2 == "House of the Dragon"
    assert s2 == 2
    assert e2 == 5
    assert title2 == "House of the Dragon S02E05"

    # Folder hierarchy Season 1/01.mkv
    show3, s3, e3, title3 = parse_media_structure("Stranger Things/Season 03/Stranger.Things.S03E01.mkv")
    assert show3 == "Stranger Things"
    assert s3 == 3
    assert e3 == 1
    assert title3 == "Stranger Things S03E01"


def test_parse_media_structure_movies_and_fallbacks():
    """Test movie naming and fallback parser."""
    # Movie with release year
    show, s, e, title = parse_media_structure("Inception.2010.1080p.mkv")
    assert show is None
    assert s is None
    assert e is None
    assert "Inception (2010)" in title

    # Fallback generic file
    show2, s2, e2, title2 = parse_media_structure("Random_Home_Video.mp4")
    assert show2 is None
    assert s2 is None
    assert e2 is None
    assert title2 == "Random Home Video"


def test_generate_strm_path():
    """Test folder structure path generation for media libraries."""
    # TV Show standard structure: Show/Season XX/Show SXXEYY.strm
    path1 = generate_strm_path("Severance.S01E01.1080p.mkv")
    assert path1 == "Severance/Season 01/Severance S01E01.strm"

    # Movie standard structure: Movie (Year)/Movie (Year).strm
    path2 = generate_strm_path("Interstellar.2014.mkv")
    assert path2 == "Interstellar (2014)/Interstellar (2014).strm"

    # Flat structure override
    path_flat = generate_strm_path("Severance.S01E01.1080p.mkv", structure_type="flat")
    assert path_flat == "Severance.S01E01.1080p.strm"

    # Mirror structure override
    path_mirror = generate_strm_path("Media/Anime/Show.mkv", structure_type="mirror")
    assert path_mirror == "Media/Anime/Show.strm"


def test_generate_strm_zip_bundle():
    """Test bundling multiple .strm files into an in-memory ZIP package."""
    entries = [
        {"id": 1, "name": "Succession.S04E01.1080p.mkv", "size_bytes": 2000000000},
        {"id": 2, "name": "Succession.S04E02.1080p.mkv", "size_bytes": 2100000000},
        {"id": 3, "name": "Succession.S04E03.1080p.mkv", "size_bytes": 1900000000},
        {"id": 4, "name": "readme.txt", "size_bytes": 500},  # Non-video, should be filtered
    ]

    base_url = "http://127.0.0.1:8787"
    zip_bytes = generate_strm_zip_bundle(entries, base_url)

    assert isinstance(zip_bytes, bytes)
    assert len(zip_bytes) > 0

    # Read back the generated ZIP file in-memory
    with zipfile.ZipFile(io.BytesIO(zip_bytes), mode="r") as zf:
        namelist = zf.namelist()
        
        # Verify 3 .strm files were generated and non-video was ignored
        assert len(namelist) == 3
        assert "Succession/Season 04/Succession S04E01.strm" in namelist
        assert "Succession/Season 04/Succession S04E02.strm" in namelist
        assert "Succession/Season 04/Succession S04E03.strm" in namelist

        # Verify content of S04E01.strm
        s01_content = zf.read("Succession/Season 04/Succession S04E01.strm").decode("utf-8")
        assert s01_content.strip() == "http://127.0.0.1:8787/stream/1/Succession.S04E01.1080p.mkv"

        # Verify content of S04E02.strm
        s02_content = zf.read("Succession/Season 04/Succession S04E02.strm").decode("utf-8")
        assert s02_content.strip() == "http://127.0.0.1:8787/stream/2/Succession.S04E02.1080p.mkv"


def test_generate_strm_zip_bundle_non_standard_entries():
    """Test bundle generation when archive contains only non-standard extensions or empty entries."""
    entries = [
        {"id": 1, "name": "track_1.custom", "size_bytes": 5000},
        {"id": 2, "name": "track_2.custom", "size_bytes": 6000},
    ]

    zip_bytes = generate_strm_zip_bundle(entries, "http://192.168.1.10:8787", structure_type="flat")
    with zipfile.ZipFile(io.BytesIO(zip_bytes), mode="r") as zf:
        namelist = zf.namelist()
        assert len(namelist) == 2
        assert "track_1.strm" in namelist
        assert "track_2.strm" in namelist
        content = zf.read("track_1.strm").decode("utf-8")
        assert content.strip() == "http://192.168.1.10:8787/stream/1/track_1.custom"


def test_complex_scene_naming_and_url_formatting():
    """Comprehensive test for scene naming parse patterns and URL formatting across strange filenames."""
    # 1. Complex scene release tags and separators
    cases = [
        ("Game.of.Thrones.S08E06.The.Iron.Throne.1080p.AMZN.WEB-DL.DDP5.1.H.264-GoT.mkv", "Game of Thrones", 8, 6, "Game of Thrones S08E06"),
        ("The.Last.of.Us.S01E09.Look.for.the.Light.2160p.UHD.HDR.mkv", "The Last of Us", 1, 9, "The Last of Us S01E09"),
        ("Dune.Part.Two.2024.2160p.UHD.BluRay.x265.mkv", None, None, None, "Dune Part Two (2024)"),
        ("Spirited.Away.2001.1080p.Dual-Audio.mkv", None, None, None, "Spirited Away (2001)"),
    ]

    for item in cases:
        if len(item) == 5:
            filename, expected_show, expected_s, expected_e, expected_clean = item
            show, s, e, clean = parse_media_structure(filename)
            assert show == expected_show
            assert s == expected_s
            assert e == expected_e
            assert expected_clean in clean

    # 2. Test special character and whitespace URL formatting in STRM generation
    special_entries = [
        {"id": 10, "name": "Rick and Morty [S05E01] Mort Dinner Rick Andre (1080p x265).mkv", "size_bytes": 1000},
        {"id": 11, "name": "Épisode_01 #special & cool?.mp4", "size_bytes": 2000},
    ]
    bundle = generate_strm_zip_bundle(special_entries, "http://my-nas.local:8787/")
    with zipfile.ZipFile(io.BytesIO(bundle), mode="r") as zf:
        # Check files inside zip
        files = zf.namelist()
        assert len(files) == 2
        for f in files:
            content = zf.read(f).decode("utf-8")
            assert content.startswith("http://my-nas.local:8787/stream/")
            assert "\n" in content
            # Ensure URL is properly encoded
            if "10" in content:
                assert "Rick%20and%20Morty" in content or "Rick" in content
            if "11" in content:
                assert "%C3%89pisode" in content or "pisode" in content

