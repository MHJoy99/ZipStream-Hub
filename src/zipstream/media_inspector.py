import io
import struct
import zlib
from typing import Dict, Any, Optional, List, Tuple

def _safe_unpack(fmt: str, data: bytes, offset: int = 0):
    size = struct.calcsize(fmt)
    if len(data) < offset + size:
        return None
    return struct.unpack_from(fmt, data, offset)


def _read_vint(data: bytes, offset: int) -> Optional[Tuple[int, int]]:
    """
    Parses an EBML variable-length integer (VINT).
    Returns (value, new_offset) or None on buffer overflow/invalid data.
    """
    if offset >= len(data):
        return None

    first_byte = data[offset]
    if first_byte == 0:
        return None

    mask = 0x80
    length = 1
    while mask > 0 and not (first_byte & mask):
        mask >>= 1
        length += 1

    if length > 8 or offset + length > len(data):
        return None

    val = first_byte & (~mask)
    for i in range(1, length):
        val = (val << 8) | data[offset + i]

    return val, offset + length


def _read_vint_int(data: bytes, offset: int, length: int) -> int:
    val = 0
    for i in range(length):
        val = (val << 8) | data[offset + i]
    return val


def _read_ebml_id(data: bytes, offset: int) -> Optional[Tuple[int, int]]:
    """
    Parses an EBML Element ID (keeps the marker bit in the ID value).
    Returns (element_id, new_offset) or None.
    """
    if offset >= len(data):
        return None

    first_byte = data[offset]
    if first_byte == 0:
        return None

    mask = 0x80
    length = 1
    while mask > 0 and not (first_byte & mask):
        mask >>= 1
        length += 1

    if length > 4 or offset + length > len(data):
        return None

    val = 0
    for i in range(length):
        val = (val << 8) | data[offset + i]

    return val, offset + length


class MediaInspector:
    """
    Ultra-fast pure Python binary media inspector for MP4, MOV, MKV, WebM.
    Parses raw header bytes without external binaries (ffmpeg/ffprobe).
    """

    @staticmethod
    def inspect_mp4(data: bytes) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "format": "mp4",
            "video_codec": None,
            "width": None,
            "height": None,
            "duration_sec": None,
            "audio_codecs": [],
        }

        timescale = None
        duration = None

        def parse_atoms(atom_data: bytes):
            nonlocal timescale, duration
            ptr = 0
            while ptr + 8 <= len(atom_data):
                size_field = struct.unpack(">I", atom_data[ptr:ptr + 4])[0]
                atom_type = atom_data[ptr + 4:ptr + 8]
                hdr_size = 8

                if size_field == 1:
                    # 64-bit large size
                    if ptr + 16 > len(atom_data):
                        break
                    atom_size = struct.unpack(">Q", atom_data[ptr + 8:ptr + 16])[0]
                    hdr_size = 16
                elif size_field == 0:
                    # Extends to EOF
                    atom_size = len(atom_data) - ptr
                else:
                    atom_size = size_field

                if atom_size < hdr_size:
                    break

                body_start = ptr + hdr_size
                body_end = min(ptr + atom_size, len(atom_data))
                body = atom_data[body_start:body_end]

                # Container atoms
                if atom_type in (b"moov", b"trak", b"mdia", b"minf", b"stbl", b"edts"):
                    parse_atoms(body)

                elif atom_type == b"mvhd":
                    if len(body) >= 20:
                        version = body[0]
                        if version == 0 and len(body) >= 20:
                            # v0: 4B flags, 4B create, 4B mod, 4B timescale, 4B duration
                            mv_timescale, mv_duration = struct.unpack(">II", body[12:20])
                            if mv_timescale > 0:
                                timescale = mv_timescale
                                duration = mv_duration
                                result["duration_sec"] = round(mv_duration / mv_timescale, 2)
                        elif version == 1 and len(body) >= 32:
                            # v1: 4B flags, 8B create, 8B mod, 4B timescale, 8B duration
                            mv_timescale, mv_duration = struct.unpack(">IQ", body[20:32])
                            if mv_timescale > 0:
                                timescale = mv_timescale
                                duration = mv_duration
                                result["duration_sec"] = round(mv_duration / mv_timescale, 2)

                elif atom_type == b"tkhd":
                    if len(body) >= 24:
                        version = body[0]
                        # Width and Height are 16.16 fixed-point numbers at the end of tkhd (last 8 bytes)
                        # Standard tkhd v0 length is 84 bytes; v1 is 96 bytes.
                        if len(body) >= 80:
                            w_fixed, h_fixed = struct.unpack(">II", body[-8:])
                            w = w_fixed >> 16
                            h = h_fixed >> 16
                            if w > 0 and h > 0 and (result["width"] is None or w > result["width"]):
                                result["width"] = w
                                result["height"] = h

                elif atom_type == b"stsd":
                    # Sample Table Sample Description
                    if len(body) >= 8:
                        # 4 bytes version/flags, 4 bytes entry count
                        entry_count = struct.unpack(">I", body[4:8])[0]
                        stsd_ptr = 8
                        for _ in range(entry_count):
                            if stsd_ptr + 8 > len(body):
                                break
                            sample_size = struct.unpack(">I", body[stsd_ptr:stsd_ptr + 4])[0]
                            format_tag = body[stsd_ptr + 4:stsd_ptr + 8]
                            sample_body = body[stsd_ptr + 8:stsd_ptr + sample_size]

                            tag_str = format_tag.decode("latin1", errors="ignore").lower()

                            # Video Codecs
                            if format_tag in (b"avc1", b"avc3", b"h264", b"H264"):
                                result["video_codec"] = "H.264"
                            elif format_tag in (b"hev1", b"hvc1", b"hevc", b"H265"):
                                result["video_codec"] = "H.265/HEVC"
                            elif format_tag in (b"av01", b"av1 "):
                                result["video_codec"] = "AV1"
                            elif format_tag in (b"vp09", b"vp08"):
                                result["video_codec"] = "VP9" if format_tag == b"vp09" else "VP8"
                            elif format_tag in (b"mp4v", b"XVID", b"xvid", b"DX50"):
                                result["video_codec"] = "MPEG-4 Visual"
                            elif format_tag in (b"apch", b"apcn", b"apcs", b"apco", b"ap4h", b"ap4x"):
                                result["video_codec"] = "ProRes"

                            # Audio Codecs
                            elif format_tag in (b"mp4a", b"aac "):
                                if "AAC" not in result["audio_codecs"]:
                                    result["audio_codecs"].append("AAC")
                            elif format_tag in (b"ac-3", b"sac3"):
                                if "AC3" not in result["audio_codecs"]:
                                    result["audio_codecs"].append("AC3")
                            elif format_tag in (b"ec-3", b"eac3"):
                                if "EAC3/DDP" not in result["audio_codecs"]:
                                    result["audio_codecs"].append("EAC3/DDP")
                            elif format_tag in (b"dtsc", b"dtsh", b"dtsl", b"dtse", b"DTS "):
                                if "DTS" not in result["audio_codecs"]:
                                    result["audio_codecs"].append("DTS")
                            elif format_tag in (b"mlpa", b"trhd"):
                                if "TrueHD" not in result["audio_codecs"]:
                                    result["audio_codecs"].append("TrueHD")
                            elif format_tag in (b"opus", b"Opus"):
                                if "Opus" not in result["audio_codecs"]:
                                    result["audio_codecs"].append("Opus")
                            elif format_tag in (b"flac", b"fLaC"):
                                if "FLAC" not in result["audio_codecs"]:
                                    result["audio_codecs"].append("FLAC")

                            # Fallback width/height inside VisualSampleEntry (offset 24 in sample_body)
                            if len(sample_body) >= 28:
                                # VisualSampleEntry: 6 reserved, 2 data_reference_index, 16 pre_defined/reserved, 2 width, 2 height
                                vw, vh = struct.unpack(">HH", sample_body[24:28])
                                if vw > 0 and vh > 0:
                                    if result["width"] is None or result["width"] == 0:
                                        result["width"] = vw
                                        result["height"] = vh

                            if sample_size <= 0:
                                break
                            stsd_ptr += sample_size

                ptr += atom_size

        parse_atoms(data)
        return result

    @staticmethod
    def inspect_mkv_webm(data: bytes) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "format": "mkv/webm",
            "video_codec": None,
            "width": None,
            "height": None,
            "duration_sec": None,
            "audio_codecs": [],
        }

        # EBML Element IDs
        ID_EBML = 0x1A45DFA3
        ID_SEGMENT = 0x18538067
        ID_INFO = 0x1549A966
        ID_TIMECODESCALE = 0x2AD7B1
        ID_DURATION = 0x4489
        ID_TRACKS = 0x1654AE6B
        ID_TRACK_ENTRY = 0xAE
        ID_TRACK_TYPE = 0x83
        ID_CODEC_ID = 0x86
        ID_VIDEO = 0xE0
        ID_PIXEL_WIDTH = 0xB0
        ID_PIXEL_HEIGHT = 0xBA
        ID_AUDIO = 0xE1
        ID_SAMPLING_FREQ = 0xB5
        ID_CHANNELS = 0x9F

        CONTAINER_IDS = {ID_EBML, ID_SEGMENT, ID_INFO, ID_TRACKS, ID_TRACK_ENTRY, ID_VIDEO, ID_AUDIO}

        # Verify EBML magic
        if len(data) < 4 or data[:4] != b"\x1A\x45\xDF\xA3":
            return result

        timecode_scale = 1000000.0  # default 1ms (1,000,000 ns)
        raw_duration = None

        def parse_elements(elem_data: bytes, depth: int = 0):
            nonlocal timecode_scale, raw_duration
            if depth > 10:
                return

            ptr = 0
            while ptr < len(elem_data):
                id_res = _read_ebml_id(elem_data, ptr)
                if not id_res:
                    break
                elem_id, ptr = id_res

                len_res = _read_vint(elem_data, ptr)
                if not len_res:
                    break
                elem_len, ptr = len_res

                if elem_len < 0 or ptr + elem_len > len(elem_data):
                    # Incomplete element (buffer truncated) -> parse inner if container, else stop
                    elem_body = elem_data[ptr:]
                else:
                    elem_body = elem_data[ptr:ptr + elem_len]

                if elem_id in CONTAINER_IDS:
                    parse_elements(elem_body, depth + 1)

                elif elem_id == ID_TIMECODESCALE:
                    if len(elem_body) > 0:
                        val = 0
                        for b in elem_body:
                            val = (val << 8) | b
                        timecode_scale = float(val)

                elif elem_id == ID_DURATION:
                    if len(elem_body) == 4:
                        raw_duration = struct.unpack(">f", elem_body)[0]
                    elif len(elem_body) == 8:
                        raw_duration = struct.unpack(">d", elem_body)[0]

                elif elem_id == ID_CODEC_ID:
                    codec_str = elem_body.decode("latin1", errors="ignore").strip("\x00")
                    # Video Codecs
                    if "AVC" in codec_str or "H264" in codec_str:
                        result["video_codec"] = "H.264"
                    elif "HEVC" in codec_str or "H265" in codec_str:
                        result["video_codec"] = "H.265/HEVC"
                    elif "AV1" in codec_str:
                        result["video_codec"] = "AV1"
                    elif "VP9" in codec_str:
                        result["video_codec"] = "VP9"
                    elif "VP8" in codec_str:
                        result["video_codec"] = "VP8"
                    elif "MPEG4" in codec_str or "XVID" in codec_str:
                        result["video_codec"] = "MPEG-4"

                    # Audio Codecs
                    elif "AAC" in codec_str:
                        if "AAC" not in result["audio_codecs"]:
                            result["audio_codecs"].append("AAC")
                    elif "AC3" in codec_str and "EAC3" not in codec_str:
                        if "AC3" not in result["audio_codecs"]:
                            result["audio_codecs"].append("AC3")
                    elif "EAC3" in codec_str or "DDP" in codec_str or "DOLBY" in codec_str:
                        if "EAC3/DDP" not in result["audio_codecs"]:
                            result["audio_codecs"].append("EAC3/DDP")
                    elif "DTS" in codec_str:
                        if "DTS" not in result["audio_codecs"]:
                            result["audio_codecs"].append("DTS")
                    elif "TRUEHD" in codec_str:
                        if "TrueHD" not in result["audio_codecs"]:
                            result["audio_codecs"].append("TrueHD")
                    elif "OPUS" in codec_str:
                        if "Opus" not in result["audio_codecs"]:
                            result["audio_codecs"].append("Opus")
                    elif "FLAC" in codec_str:
                        if "FLAC" not in result["audio_codecs"]:
                            result["audio_codecs"].append("FLAC")
                    elif "VORBIS" in codec_str:
                        if "Vorbis" not in result["audio_codecs"]:
                            result["audio_codecs"].append("Vorbis")

                elif elem_id == ID_PIXEL_WIDTH:
                    val = 0
                    for b in elem_body:
                        val = (val << 8) | b
                    if val > 0:
                        result["width"] = val

                elif elem_id == ID_PIXEL_HEIGHT:
                    val = 0
                    for b in elem_body:
                        val = (val << 8) | b
                    if val > 0:
                        result["height"] = val

                if elem_len < 0 or ptr + elem_len > len(elem_data):
                    break
                ptr += elem_len

        parse_elements(data)

        if raw_duration is not None and timecode_scale is not None:
            # duration_sec = (raw_duration * timecode_scale) / 1,000,000,000
            result["duration_sec"] = round((raw_duration * timecode_scale) / 1_000_000_000.0, 2)

        return result


def inspect_media_header(reader, entry: Dict[str, Any], initial_bytes: int = 65536) -> Dict[str, Any]:
    """
    Inspects video file metadata directly from a remote ZIP entry via HTTP Range requests.
    
    1. Fetches first `initial_bytes` (default 64KB).
    2. Parses container (MP4 / MOV / MKV / WebM).
    3. Handles fallback when moov atom is located at the tail of MP4 file.
    
    Returns structured media details:
      {
        "format": "mp4" | "mkv/webm" | "unknown",
        "video_codec": str | None,
        "width": int | None,
        "height": int | None,
        "duration_sec": float | None,
        "audio_codecs": List[str],
        "size_mb": float,
        "compressed": bool
      }
    """
    output: Dict[str, Any] = {
        "format": "unknown",
        "video_codec": None,
        "width": None,
        "height": None,
        "duration_sec": None,
        "audio_codecs": [],
        "size_mb": entry.get("size_mb", 0.0),
        "compressed": entry.get("method", 0) != 0,
    }

    try:
        data_start = reader.get_data_offset(entry)
        comp_size = entry.get("comp_size_bytes") or entry.get("size_bytes", 0)
        if comp_size <= 0:
            return output

        fetch_size = min(initial_bytes, comp_size)
        
        # If compressed (DEFLATE), fetch slightly larger buffer and decompress stream head
        method = entry.get("method", 0)
        if method == 8:
            raw_data = reader._fetch_range(data_start, data_start + min(fetch_size * 2, comp_size) - 1)
            try:
                decompressor = zlib.decompressobj(-15)
                head_data = decompressor.decompress(raw_data, initial_bytes)
            except Exception:
                try:
                    head_data = zlib.decompress(raw_data)
                except Exception:
                    return output
        elif method == 0:
            head_data = reader._fetch_range(data_start, data_start + fetch_size - 1)
        else:
            return output

        if not head_data:
            return output

        # Detect container type
        is_mkv = head_data.startswith(b"\x1A\x45\xDF\xA3")
        is_mp4 = len(head_data) >= 8 and head_data[4:8] in (b"ftyp", b"moov", b"mdat", b"free", b"skip")

        if is_mkv:
            mkv_info = MediaInspector.inspect_mkv_webm(head_data)
            output.update(mkv_info)

        elif is_mp4:
            mp4_info = MediaInspector.inspect_mp4(head_data)
            output.update(mp4_info)

            # Robust fallback: If moov atom is located at the tail of MP4 (common in un-optimized files)
            # and video_codec or duration wasn't found in the first 64KB, fetch last 128KB
            if (output.get("video_codec") is None or output.get("duration_sec") is None) and method == 0:
                if comp_size > fetch_size:
                    tail_fetch = min(131072, comp_size)
                    tail_start = data_start + comp_size - tail_fetch
                    tail_data = reader._fetch_range(tail_start, data_start + comp_size - 1)
                    
                    # Look for moov in tail
                    moov_idx = tail_data.find(b"moov")
                    if moov_idx != -1 and moov_idx >= 4:
                        tail_info = MediaInspector.inspect_mp4(tail_data[moov_idx - 4:])
                        if tail_info.get("video_codec"):
                            output["video_codec"] = tail_info["video_codec"]
                        if tail_info.get("width") and not output.get("width"):
                            output["width"] = tail_info["width"]
                            output["height"] = tail_info["height"]
                        if tail_info.get("duration_sec"):
                            output["duration_sec"] = tail_info["duration_sec"]
                        if tail_info.get("audio_codecs"):
                            for ac in tail_info["audio_codecs"]:
                                if ac not in output["audio_codecs"]:
                                    output["audio_codecs"].append(ac)

    except Exception as e:
        output["error"] = str(e)

    return output
