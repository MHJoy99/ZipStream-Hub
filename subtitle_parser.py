"""
ZipStreamHub Subtitle Parser & Matcher
Detects and pairs subtitle tracks with archive video entries, and converts SRT/ASS subtitles to standard WebVTT format.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


SUBTITLE_EXTENSIONS = {".srt", ".vtt", ".ass", ".ssa"}
VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".webm", ".mov", ".ts", ".m4v", ".flv"}

# Common 2-letter / 3-letter language codes and names
LANG_MAP = {
    "en": "English", "eng": "English", "english": "English",
    "ja": "Japanese", "jp": "Japanese", "jpn": "Japanese", "japanese": "Japanese",
    "zh": "Chinese", "chi": "Chinese", "zho": "Chinese", "chs": "Chinese (Simplified)", "cht": "Chinese (Traditional)", "chinese": "Chinese",
    "es": "Spanish", "spa": "Spanish", "spanish": "Spanish",
    "fr": "French", "fre": "French", "fra": "French", "french": "French",
    "de": "German", "ger": "German", "deu": "German", "german": "German",
    "it": "Italian", "ita": "Italian", "italian": "Italian",
    "pt": "Portuguese", "por": "Portuguese", "portuguese": "Portuguese",
    "ru": "Russian", "rus": "Russian", "russian": "Russian",
    "ko": "Korean", "kor": "Korean", "korean": "Korean",
    "ar": "Arabic", "ara": "Arabic", "arabic": "Arabic",
    "hi": "Hindi", "hin": "Hindi", "hindi": "Hindi",
    "th": "Thai", "tha": "Thai", "thai": "Thai",
    "vi": "Vietnamese", "vie": "Vietnamese", "vietnamese": "Vietnamese",
    "id": "Indonesian", "ind": "Indonesian", "indonesian": "Indonesian",
    "und": "Undetermined", "sub": "Subtitle", "subs": "Subtitles",
}


@dataclass
class SubtitleTrack:
    id: int
    name: str
    extension: str
    size_bytes: int
    language: str
    label: str
    is_default: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "extension": self.extension,
            "size_bytes": self.size_bytes,
            "language": self.language,
            "label": self.label,
            "is_default": self.is_default,
        }


def _extract_episode_number(filename: str) -> Optional[int]:
    """
    Extract episode number from filename patterns like S01E02, E02, EP02, 01.srt, etc.
    """
    base = os.path.splitext(os.path.basename(filename))[0]
    
    # Pattern 1: S01E02, s1e2, S1.E2, etc.
    m = re.search(r"[Ss]\d{1,2}[ ._-]*[Ee](\d{1,3})", base)
    if m:
        return int(m.group(1))
        
    # Pattern 2: EP02, Ep. 02, Episode 02
    m = re.search(r"(?:ep|episode)[ ._-]*(\d{1,3})", base, re.IGNORECASE)
    if m:
        return int(m.group(1))

    # Pattern 3: Standalone numbers like "01", "1", "01.en", "[01]"
    m = re.search(r"(?:^|[ ._\[\(-])(\d{1,3})(?:[ ._\]\)-]|$)", base)
    if m:
        return int(m.group(1))

    return None


def _clean_stem(filename: str) -> str:
    """Removes extension and common trailing language tags for stem matching."""
    stem = os.path.splitext(os.path.basename(filename))[0]
    # Remove language tag if present at end (e.g. .en, .eng, _en, -eng)
    stem = re.sub(r"[._ -](?:en|eng|ja|jpn|chs|cht|zh|es|fr|de|ru|ko|und|default|forced)$", "", stem, flags=re.IGNORECASE)
    return stem.lower().strip()


def _detect_language(sub_filename: str) -> Tuple[str, str]:
    """
    Detects language code and human-readable label from subtitle path.
    Returns (lang_code, label).
    """
    stem = os.path.splitext(os.path.basename(sub_filename))[0]
    parts = re.split(r"[._ -]+", stem.lower())
    
    # Check parts from right to left
    for part in reversed(parts):
        if part in LANG_MAP:
            return part, LANG_MAP[part]
            
    # Check parent directory name (e.g. Subs/English/01.srt or Subs/en/01.srt)
    parent = os.path.basename(os.path.dirname(sub_filename)).lower()
    if parent in LANG_MAP:
        return parent, LANG_MAP[parent]
    for k, v in LANG_MAP.items():
        if k in parent:
            return k, v

    return "und", "Subtitle"


def is_subtitle_file(filename: str) -> bool:
    """Check if filename has a supported subtitle extension."""
    ext = os.path.splitext(filename)[1].lower()
    return ext in SUBTITLE_EXTENSIONS


def is_video_file(filename: str) -> bool:
    """Check if filename has a recognized video extension."""
    ext = os.path.splitext(filename)[1].lower()
    return ext in VIDEO_EXTENSIONS


def match_subtitles_for_video(video_entry: Dict[str, Any], all_entries: List[Dict[str, Any]]) -> List[SubtitleTrack]:
    """
    Matches subtitle entries from an archive to a given video entry.
    Supports:
      - Direct stem match: `Movie.mkv` <-> `Movie.srt`, `Movie.en.srt`
      - Episode number match: `Show.S01E01.mkv` <-> `Subs/01.srt`, `Subs/01.en.ass`, `Show.S01E01.srt`
      - Directory grouping: `Subs/S01E01.srt`
      - Single video fallback: If only 1 video and standalone subtitles exist.
    """
    video_name = video_entry.get("name", "")
    video_stem = _clean_stem(video_name)
    video_ep = _extract_episode_number(video_name)
    
    all_videos = [e for e in all_entries if is_video_file(e.get("name", ""))]
    sub_entries = [e for e in all_entries if is_subtitle_file(e.get("name", ""))]
    
    matched_tracks: List[SubtitleTrack] = []
    
    for sub in sub_entries:
        sub_name = sub.get("name", "")
        sub_ext = os.path.splitext(sub_name)[1].lower()
        sub_stem = _clean_stem(sub_name)
        sub_ep = _extract_episode_number(sub_name)
        
        is_match = False
        
        # 1. Exact or prefix stem match (e.g. video.mkv and video.en.srt)
        if sub_stem == video_stem or (video_stem and sub_stem.startswith(video_stem)):
            is_match = True
        # 2. Episode number match if both video and sub have episode numbers
        elif video_ep is not None and sub_ep is not None:
            if video_ep == sub_ep:
                is_match = True
            else:
                is_match = False
        # 3. Single video archive with subtitles fallback (only if sub doesn't belong to a different episode)
        elif len(all_videos) == 1 and (video_ep is None or sub_ep is None or video_ep == sub_ep):
            is_match = True

        if is_match:
            lang_code, lang_label = _detect_language(sub_name)
            is_default = len(matched_tracks) == 0 and (lang_code in ("en", "eng") or len(sub_entries) == 1)
            
            # Format label nicely with episode/language if available
            label = f"{lang_label} ({sub_ext.lstrip('.').upper()})"
            
            matched_tracks.append(
                SubtitleTrack(
                    id=sub.get("id", 0),
                    name=sub_name,
                    extension=sub_ext,
                    size_bytes=sub.get("size_bytes", 0),
                    language=lang_code,
                    label=label,
                    is_default=is_default,
                )
            )

    return matched_tracks


def pair_archive_subtitles(entries: List[Dict[str, Any]]) -> Dict[int, List[Dict[str, Any]]]:
    """
    Scans all archive entries, finds videos, and maps each video ID to its matched subtitle tracks.
    Returns: {video_id: [subtitle_dict, ...]}
    """
    result: Dict[int, List[Dict[str, Any]]] = {}
    video_entries = [e for e in entries if is_video_file(e.get("name", ""))]

    for v in video_entries:
        tracks = match_subtitles_for_video(v, entries)
        result[v.get("id", 0)] = [t.to_dict() for t in tracks]

    return result


def _format_vtt_timestamp(hours: int, minutes: int, seconds: int, milliseconds: int) -> str:
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"


def srt_to_vtt(srt_content: str) -> str:
    """
    Converts SubRip (.srt) text content into WebVTT (.vtt) format.
    Ensures 'WEBVTT' header, converts comma timestamps (00:01:20,500) to dot (00:01:20.500),
    and removes any invalid/corrupted formatting.
    """
    if not srt_content.strip():
        return "WEBVTT\n\n"

    # Normalize line endings
    text = srt_content.replace("\r\n", "\n").replace("\r", "\n").strip()
    
    # Replace timestamps 00:00:00,000 --> 00:00:00,000
    # Handles both 2-part (00:00,000) and 3-part (00:00:00,000)
    def repl_ts(match: re.Match) -> str:
        s_h, s_m, s_s, s_ms, e_h, e_m, e_s, e_ms = match.groups()
        s_h = int(s_h) if s_h else 0
        e_h = int(e_h) if e_h else 0
        s_formatted = _format_vtt_timestamp(s_h, int(s_m), int(s_s), int(s_ms.ljust(3, "0")[:3]))
        e_formatted = _format_vtt_timestamp(e_h, int(e_m), int(e_s), int(e_ms.ljust(3, "0")[:3]))
        return f"{s_formatted} --> {e_formatted}"

    ts_pattern = re.compile(
        r"(?:(\d{1,2}):)?(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(?:(\d{1,2}):)?(\d{2}):(\d{2})[,.](\d{1,3})"
    )

    lines = text.split("\n")
    vtt_lines = ["WEBVTT", ""]
    
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        # Optional cue index (digits only)
        if line.isdigit() and i + 1 < len(lines) and ts_pattern.search(lines[i + 1]):
            i += 1
            line = lines[i].strip()

        # Check timestamp
        if ts_pattern.search(line):
            cue_line = ts_pattern.sub(repl_ts, line)
            vtt_lines.append(cue_line)
            i += 1
            # Gather subtitle text until empty line or next index/timestamp
            cue_text = []
            while i < len(lines) and lines[i].strip():
                # Check if next block has started without blank line
                if ts_pattern.search(lines[i]) or (lines[i].strip().isdigit() and i + 1 < len(lines) and ts_pattern.search(lines[i+1])):
                    break
                cue_text.append(lines[i])
                i += 1
            vtt_lines.extend(cue_text)
            vtt_lines.append("")
        else:
            i += 1

    return "\n".join(vtt_lines).strip() + "\n"


def ass_to_vtt(ass_content: str) -> str:
    """
    Converts Advanced SubStation Alpha (.ass / .ssa) content to WebVTT format.
    Strips ASS styling tags (e.g. {\\pos(x,y)}, {\\i1}, {\\c&H...&}) and converts \\N to newlines.
    """
    if not ass_content.strip():
        return "WEBVTT\n\n"

    lines = ass_content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    vtt_lines = ["WEBVTT", ""]

    def parse_ass_time(ts_str: str) -> str:
        # Format: H:MM:SS.cs (e.g. 0:01:23.45)
        parts = ts_str.strip().split(":")
        if len(parts) == 3:
            h = int(parts[0])
            m = int(parts[1])
            s_parts = parts[2].split(".")
            s = int(s_parts[0])
            cs = s_parts[1] if len(s_parts) > 1 else "0"
            ms = int(cs.ljust(3, "0")[:3])
            return _format_vtt_timestamp(h, m, s, ms)
        return "00:00:00.000"

    in_events = False
    format_indices: Dict[str, int] = {}

    for line in lines:
        line_clean = line.strip()
        if not line_clean or line_clean.startswith(";"):
            continue

        if line_clean.lower().startswith("[events]"):
            in_events = True
            continue

        if line_clean.lower().startswith("[") and in_events and not line_clean.lower().startswith("[events]"):
            in_events = False
            continue

        if in_events:
            if line_clean.lower().startswith("format:"):
                # e.g. Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
                fields = [f.strip().lower() for f in line_clean[7:].split(",")]
                format_indices = {field: idx for idx, field in enumerate(fields)}
                continue

            if line_clean.lower().startswith("dialogue:"):
                raw_data = line_clean[9:].strip()
                # Dialogue line can have commas in the text field; split only up to format count
                max_splits = len(format_indices) - 1 if format_indices else 9
                parts = [p.strip() for p in raw_data.split(",", max_splits)]

                if not format_indices:
                    # Default ASS format fallback: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
                    if len(parts) < 10:
                        continue
                    start_str, end_str = parts[1], parts[2]
                    text_str = parts[9]
                else:
                    start_idx = format_indices.get("start", 1)
                    end_idx = format_indices.get("end", 2)
                    text_idx = format_indices.get("text", len(parts) - 1)
                    if len(parts) <= max(start_idx, end_idx, text_idx):
                        continue
                    start_str = parts[start_idx]
                    end_str = parts[end_idx]
                    text_str = parts[text_idx]

                vtt_start = parse_ass_time(start_str)
                vtt_end = parse_ass_time(end_str)

                # Strip ASS override tags like {\an8}, {\pos(10,20)}, {\c&H0000FF&}
                clean_text = re.sub(r"\{[^}]*\}", "", text_str)
                # Convert \N and \n to newline
                clean_text = clean_text.replace(r"\N", "\n").replace(r"\n", "\n").strip()

                if clean_text:
                    vtt_lines.append(f"{vtt_start} --> {vtt_end}")
                    vtt_lines.append(clean_text)
                    vtt_lines.append("")

    return "\n".join(vtt_lines).strip() + "\n"


def convert_to_vtt(content: str, filename_or_ext: str) -> str:
    """
    Converts subtitle text content from SRT, ASS/SSA, or VTT to clean WebVTT format.
    """
    ext = os.path.splitext(filename_or_ext)[1].lower() if "." in filename_or_ext else f".{filename_or_ext.lower()}"
    
    if ext in (".ass", ".ssa"):
        return ass_to_vtt(content)
    elif ext == ".srt":
        return srt_to_vtt(content)
    elif ext == ".vtt":
        text = content.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not text.startswith("WEBVTT"):
            text = "WEBVTT\n\n" + text
        return text + "\n"
    else:
        # Default fallback: try srt conversion
        return srt_to_vtt(content)
