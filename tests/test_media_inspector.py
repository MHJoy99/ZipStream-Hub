import pytest
import struct
import sys
from pathlib import Path
from unittest.mock import MagicMock

# Ensure parent directory is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from media_inspector import MediaInspector, inspect_media_header


def _create_mock_mp4_header() -> bytes:
    """Creates a minimal valid MP4 binary header with ftyp, moov, mvhd, trak, tkhd, stbl, stsd."""
    # ftyp
    ftyp_data = b"isom" + struct.pack(">I", 512) + b"isomiso2avc1mp41"
    ftyp = struct.pack(">I", 8 + len(ftyp_data)) + b"ftyp" + ftyp_data

    # mvhd (timescale=1000, duration=60000 -> 60.0s)
    # v0: 4B flags, 4B create, 4B mod, 4B timescale, 4B duration, 80B rest
    mvhd_body = b"\x00\x00\x00\x00" + struct.pack(">IIII", 0, 0, 1000, 60000) + (b"\x00" * 80)
    mvhd = struct.pack(">I", 8 + len(mvhd_body)) + b"mvhd" + mvhd_body

    # tkhd with width=1920, height=1080 (16.16 fixed-point: 1920 << 16, 1080 << 16)
    # 84 bytes standard body
    tkhd_body = (b"\x00" * 76) + struct.pack(">II", 1920 << 16, 1080 << 16)
    tkhd = struct.pack(">I", 8 + len(tkhd_body)) + b"tkhd" + tkhd_body

    # stsd with avc1 (H.264) video entry + aac (AAC) audio entry
    # VisualSampleEntry for avc1: 6 reserved, 2 dref_idx, 16 pre_def, 2 w, 2 h, 50B rest
    avc1_body = (b"\x00" * 24) + struct.pack(">HH", 1920, 1080) + (b"\x00" * 50)
    avc1_entry = struct.pack(">I", 8 + len(avc1_body)) + b"avc1" + avc1_body

    # AudioSampleEntry for mp4a
    mp4a_body = b"\x00" * 28
    mp4a_entry = struct.pack(">I", 8 + len(mp4a_body)) + b"mp4a" + mp4a_body

    stsd_body = b"\x00\x00\x00\x00" + struct.pack(">I", 2) + avc1_entry + mp4a_entry
    stsd = struct.pack(">I", 8 + len(stsd_body)) + b"stsd" + stsd_body

    stbl = struct.pack(">I", 8 + len(stsd)) + b"stbl" + stsd
    minf = struct.pack(">I", 8 + len(stbl)) + b"minf" + stbl
    mdia = struct.pack(">I", 8 + len(minf)) + b"mdia" + minf
    trak = struct.pack(">I", 8 + len(tkhd) + len(mdia)) + b"trak" + tkhd + mdia

    moov = struct.pack(">I", 8 + len(mvhd) + len(trak)) + b"moov" + mvhd + trak
    return ftyp + moov


def _create_mock_mkv_header() -> bytes:
    """Creates a minimal valid MKV EBML header with Track entries for HEVC (4K) and EAC3."""
    # EBML Header: ID 0x1A45DFA3, size 0 (or minimal), DocType = matroska
    ebml_magic = b"\x1A\x45\xDF\xA3"
    ebml_body = b"\x42\x82\x88matroska"
    ebml_header = ebml_magic + bytes([0x80 | len(ebml_body)]) + ebml_body

    # Info: Segment Duration (double 120.0s = 120000ms), TimecodeScale 1000000
    info_body = (
        b"\x2A\xD7\xB1" + bytes([0x80 | 3]) + b"\x0F\x42\x40" +  # TimecodeScale = 1,000,000 ns (1ms)
        b"\x44\x89" + bytes([0x80 | 8]) + struct.pack(">d", 120000.0)  # Duration = 120000 ms
    )
    info_elem = b"\x15\x49\xA9\x66" + bytes([0x80 | len(info_body)]) + info_body

    # Track 1: Video (HEVC, 3840x2160)
    video_sub = (
        b"\xB0" + bytes([0x80 | 2]) + struct.pack(">H", 3840) +  # PixelWidth = 3840 (0x0F00)
        b"\xBA" + bytes([0x80 | 2]) + struct.pack(">H", 2160)    # PixelHeight = 2160 (0x0870)
    )
    video_elem = b"\xE0" + bytes([0x80 | len(video_sub)]) + video_sub

    codec_str = b"V_MPEGH/ISO/HEVC"
    track1_body = (
        b"\x83\x81\x01" +  # TrackType = 1 (Video)
        b"\x86" + bytes([0x80 | len(codec_str)]) + codec_str +  # CodecID
        video_elem
    )
    track1 = b"\xAE" + bytes([0x80 | len(track1_body)]) + track1_body

    # Track 2: Audio (EAC3)
    audio_codec_str = b"A_EAC3/DDP"
    track2_body = (
        b"\x83\x81\x02" +  # TrackType = 2 (Audio)
        b"\x86" + bytes([0x80 | len(audio_codec_str)]) + audio_codec_str  # CodecID
    )
    track2 = b"\xAE" + bytes([0x80 | len(track2_body)]) + track2_body

    tracks_body = track1 + track2
    tracks_elem = b"\x16\x54\xAE\x6B" + bytes([0x80 | len(tracks_body)]) + tracks_body

    # Segment
    segment_body = info_elem + tracks_elem
    segment_elem = b"\x18\x53\x80\x67" + bytes([0x80 | len(segment_body)]) + segment_body

    return ebml_header + segment_elem


def test_mp4_header_parsing():
    raw_mp4 = _create_mock_mp4_header()
    info = MediaInspector.inspect_mp4(raw_mp4)

    assert info["format"] == "mp4"
    assert info["video_codec"] == "H.264"
    assert info["width"] == 1920
    assert info["height"] == 1080
    assert info["duration_sec"] == 60.0
    assert "AAC" in info["audio_codecs"]


def test_mkv_header_parsing():
    raw_mkv = _create_mock_mkv_header()
    info = MediaInspector.inspect_mkv_webm(raw_mkv)

    assert info["format"] == "mkv/webm"
    assert info["video_codec"] == "H.265/HEVC"
    assert info["width"] == 3840
    assert info["height"] == 2160
    assert info["duration_sec"] == 120.0
    assert "EAC3/DDP" in info["audio_codecs"]


def test_inspect_media_header_remote_reader():
    raw_mp4 = _create_mock_mp4_header()
    
    mock_reader = MagicMock()
    mock_reader.get_data_offset.return_value = 1000
    mock_reader._fetch_range.return_value = raw_mp4

    entry = {
        "name": "movie.mp4",
        "size_bytes": len(raw_mp4),
        "comp_size_bytes": len(raw_mp4),
        "size_mb": 1.5,
        "method": 0
    }

    result = inspect_media_header(mock_reader, entry)

    assert result["format"] == "mp4"
    assert result["video_codec"] == "H.264"
    assert result["width"] == 1920
    assert result["height"] == 1080
    assert result["duration_sec"] == 60.0
    assert "AAC" in result["audio_codecs"]
    assert result["compressed"] is False


def test_inspect_media_header_tail_fallback():
    # MP4 with ftyp + mdat at start, and moov at the tail
    ftyp = struct.pack(">I", 12) + b"ftypisom"
    mdat = struct.pack(">I", 65500) + b"mdat" + (b"\x00" * (65500 - 8))
    
    # moov at tail
    mvhd_body = b"\x00\x00\x00\x00" + struct.pack(">IIII", 0, 0, 1000, 30000) + (b"\x00" * 80)
    mvhd = struct.pack(">I", 8 + len(mvhd_body)) + b"mvhd" + mvhd_body
    
    av01_body = (b"\x00" * 24) + struct.pack(">HH", 2560, 1440) + (b"\x00" * 50)
    av01_entry = struct.pack(">I", 8 + len(av01_body)) + b"av01" + av01_body
    stsd_body = b"\x00\x00\x00\x00" + struct.pack(">I", 1) + av01_entry
    stsd = struct.pack(">I", 8 + len(stsd_body)) + b"stsd" + stsd_body
    stbl = struct.pack(">I", 8 + len(stsd)) + b"stbl" + stsd
    minf = struct.pack(">I", 8 + len(stbl)) + b"minf" + stbl
    mdia = struct.pack(">I", 8 + len(minf)) + b"mdia" + minf
    trak = struct.pack(">I", 8 + len(mdia)) + b"trak" + mdia
    moov = struct.pack(">I", 8 + len(mvhd) + len(trak)) + b"moov" + mvhd + trak

    head_bytes = ftyp + mdat[:60000]
    tail_bytes = b"\x00" * 500 + moov

    mock_reader = MagicMock()
    mock_reader.get_data_offset.return_value = 5000
    
    def mock_fetch(start, end):
        if start == 5000:
            return head_bytes
        else:
            return tail_bytes
            
    mock_reader._fetch_range.side_effect = mock_fetch

    entry = {
        "name": "sample_tail_moov.mp4",
        "size_bytes": 1000000,
        "comp_size_bytes": 1000000,
        "size_mb": 1.0,
        "method": 0
    }

    result = inspect_media_header(mock_reader, entry)
    assert result["format"] == "mp4"
    assert result["video_codec"] == "AV1"
    assert result["width"] == 2560
    assert result["height"] == 1440
    assert result["duration_sec"] == 30.0


def test_codec_detection_variations_mp4():
    """Verify various MP4 codec tags like HEVC, VP9, ProRes, AC3, DTS, TrueHD."""
    codecs_to_test = [
        (b"hev1", "H.265/HEVC"),
        (b"vp09", "VP9"),
        (b"apch", "ProRes"),
        (b"mp4v", "MPEG-4 Visual"),
    ]

    for tag, expected_name in codecs_to_test:
        # ftyp
        ftyp = struct.pack(">I", 12) + b"ftypisom"
        
        # stsd entry
        body = (b"\x00" * 24) + struct.pack(">HH", 1280, 720) + (b"\x00" * 50)
        entry = struct.pack(">I", 8 + len(body)) + tag + body
        
        # Audio entries
        audio1 = struct.pack(">I", 8 + 28) + b"ac-3" + (b"\x00" * 28)
        audio2 = struct.pack(">I", 8 + 28) + b"dtsc" + (b"\x00" * 28)
        audio3 = struct.pack(">I", 8 + 28) + b"trhd" + (b"\x00" * 28)
        
        stsd_body = b"\x00\x00\x00\x00" + struct.pack(">I", 4) + entry + audio1 + audio2 + audio3
        stsd = struct.pack(">I", 8 + len(stsd_body)) + b"stsd" + stsd_body
        stbl = struct.pack(">I", 8 + len(stsd)) + b"stbl" + stsd
        minf = struct.pack(">I", 8 + len(stbl)) + b"minf" + stbl
        mdia = struct.pack(">I", 8 + len(minf)) + b"mdia" + minf
        trak = struct.pack(">I", 8 + len(mdia)) + b"trak" + mdia
        moov = struct.pack(">I", 8 + len(trak)) + b"moov" + trak

        raw_data = ftyp + moov
        info = MediaInspector.inspect_mp4(raw_data)
        assert info["video_codec"] == expected_name
        assert "AC3" in info["audio_codecs"]
        assert "DTS" in info["audio_codecs"]
        assert "TrueHD" in info["audio_codecs"]


def test_codec_detection_variations_mkv():
    """Verify various MKV codec IDs like VP9, AV1, AAC, DTS, FLAC, Opus, TrueHD."""
    ebml_magic = b"\x1A\x45\xDF\xA3"
    ebml_body = b"\x42\x82\x88matroska"
    ebml_header = ebml_magic + bytes([0x80 | len(ebml_body)]) + ebml_body

    # Video: AV1, 1920x1080
    video_sub = (
        b"\xB0" + bytes([0x80 | 2]) + struct.pack(">H", 1920) +
        b"\xBA" + bytes([0x80 | 2]) + struct.pack(">H", 1080)
    )
    video_elem = b"\xE0" + bytes([0x80 | len(video_sub)]) + video_sub
    codec_str = b"V_AV1"
    track1_body = (
        b"\x83\x81\x01" +
        b"\x86" + bytes([0x80 | len(codec_str)]) + codec_str +
        video_elem
    )
    track1 = b"\xAE" + bytes([0x80 | len(track1_body)]) + track1_body

    # Audio: FLAC
    audio_codec_str = b"A_FLAC"
    track2_body = (
        b"\x83\x81\x02" +
        b"\x86" + bytes([0x80 | len(audio_codec_str)]) + audio_codec_str
    )
    track2 = b"\xAE" + bytes([0x80 | len(track2_body)]) + track2_body

    # Audio: Opus
    opus_codec_str = b"A_OPUS"
    track3_body = (
        b"\x83\x81\x02" +
        b"\x86" + bytes([0x80 | len(opus_codec_str)]) + opus_codec_str
    )
    track3 = b"\xAE" + bytes([0x80 | len(track3_body)]) + track3_body

    tracks_body = track1 + track2 + track3
    tracks_elem = b"\x16\x54\xAE\x6B" + bytes([0x80 | len(tracks_body)]) + tracks_body
    segment_elem = b"\x18\x53\x80\x67" + bytes([0x80 | len(tracks_elem)]) + tracks_elem

    raw_mkv = ebml_header + segment_elem
    info = MediaInspector.inspect_mkv_webm(raw_mkv)
    assert info["video_codec"] == "AV1"
    assert info["width"] == 1920
    assert info["height"] == 1080
    assert "FLAC" in info["audio_codecs"]
    assert "Opus" in info["audio_codecs"]

