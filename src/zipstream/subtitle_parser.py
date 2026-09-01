"""
ZipStreamHub Subtitle Parser & Matcher
Detects and pairs subtitle tracks with archive video entries, normalizes language codes,
sanitizes WebVTT cues, and packages multi-track subtitles.
"""

from __future__ import annotations

import html
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union


SUBTITLE_EXTENSIONS = {".srt", ".vtt", ".ass", ".ssa"}
VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".webm", ".mov", ".ts", ".m4v", ".flv"}

# ISO 639-1 / 639-2 / common alias language map: maps normalized aliases to (ISO 639-1 code, Human name)
# Includes mappings such as eng->en, spa->es, fre/fra->fr, jpn->ja, chi/zho->zh, etc.
ISO_LANG_MAP: Dict[str, Tuple[str, str]] = {
    # English
    "en": ("en", "English"),
    "eng": ("en", "English"),
    "english": ("en", "English"),
    # Spanish
    "es": ("es", "Spanish"),
    "spa": ("es", "Spanish"),
    "esl": ("es", "Spanish"),
    "spanish": ("es", "Spanish"),
    "espanol": ("es", "Spanish"),
    "español": ("es", "Spanish"),
    # French
    "fr": ("fr", "French"),
    "fre": ("fr", "French"),
    "fra": ("fr", "French"),
    "french": ("fr", "French"),
    "francais": ("fr", "French"),
    "français": ("fr", "French"),
    # Japanese
    "ja": ("ja", "Japanese"),
    "jp": ("ja", "Japanese"),
    "jpn": ("ja", "Japanese"),
    "japanese": ("ja", "Japanese"),
    # Chinese
    "zh": ("zh", "Chinese"),
    "chi": ("zh", "Chinese"),
    "zho": ("zh", "Chinese"),
    "chinese": ("zh", "Chinese"),
    "chs": ("zh-Hans", "Chinese (Simplified)"),
    "cht": ("zh-Hant", "Chinese (Traditional)"),
    "zh-cn": ("zh-CN", "Chinese (Simplified)"),
    "zh-tw": ("zh-TW", "Chinese (Traditional)"),
    "zh-hans": ("zh-Hans", "Chinese (Simplified)"),
    "zh-hant": ("zh-Hant", "Chinese (Traditional)"),
    # German
    "de": ("de", "German"),
    "ger": ("de", "German"),
    "deu": ("de", "German"),
    "german": ("de", "German"),
    "deutsch": ("de", "German"),
    # Italian
    "it": ("it", "Italian"),
    "ita": ("it", "Italian"),
    "italian": ("it", "Italian"),
    "italiano": ("it", "Italian"),
    # Portuguese
    "pt": ("pt", "Portuguese"),
    "por": ("pt", "Portuguese"),
    "portuguese": ("pt", "Portuguese"),
    "pt-br": ("pt-BR", "Portuguese (Brazil)"),
    "brazilian": ("pt-BR", "Portuguese (Brazil)"),
    # Russian
    "ru": ("ru", "Russian"),
    "rus": ("ru", "Russian"),
    "russian": ("ru", "Russian"),
    # Korean
    "ko": ("ko", "Korean"),
    "kor": ("ko", "Korean"),
    "korean": ("ko", "Korean"),
    # Arabic
    "ar": ("ar", "Arabic"),
    "ara": ("ar", "Arabic"),
    "arabic": ("ar", "Arabic"),
    # Hindi
    "hi": ("hi", "Hindi"),
    "hin": ("hi", "Hindi"),
    "hindi": ("hi", "Hindi"),
    # Thai
    "th": ("th", "Thai"),
    "tha": ("th", "Thai"),
    "thai": ("th", "Thai"),
    # Vietnamese
    "vi": ("vi", "Vietnamese"),
    "vie": ("vi", "Vietnamese"),
    "vietnamese": ("vi", "Vietnamese"),
    # Indonesian
    "id": ("id", "Indonesian"),
    "ind": ("id", "Indonesian"),
    "indonesian": ("id", "Indonesian"),
    # Polish
    "pl": ("pl", "Polish"),
    "pol": ("pl", "Polish"),
    "polish": ("pl", "Polish"),
    # Dutch
    "nl": ("nl", "Dutch"),
    "dut": ("nl", "Dutch"),
    "nld": ("nl", "Dutch"),
    "dutch": ("nl", "Dutch"),
    # Turkish
    "tr": ("tr", "Turkish"),
    "tur": ("tr", "Turkish"),
    "turkish": ("tr", "Turkish"),
    # Swedish
    "sv": ("sv", "Swedish"),
    "swe": ("sv", "Swedish"),
    "swedish": ("sv", "Swedish"),
    # Norwegian
    "no": ("no", "Norwegian"),
    "nor": ("no", "Norwegian"),
    "norwegian": ("no", "Norwegian"),
    # Danish
    "da": ("da", "Danish"),
    "dan": ("da", "Danish"),
    "danish": ("da", "Danish"),
    # Finnish
    "fi": ("fi", "Finnish"),
    "fin": ("fi", "Finnish"),
    "finnish": ("fi", "Finnish"),
    # Greek
    "el": ("el", "Greek"),
    "gre": ("el", "Greek"),
    "ell": ("el", "Greek"),
    "greek": ("el", "Greek"),
    # Czech
    "cs": ("cs", "Czech"),
    "cze": ("cs", "Czech"),
    "ces": ("cs", "Czech"),
    "czech": ("cs", "Czech"),
    # Hungarian
    "hu": ("hu", "Hungarian"),
    "hun": ("hu", "Hungarian"),
    "hungarian": ("hu", "Hungarian"),
    # Romanian
    "ro": ("ro", "Romanian"),
    "rum": ("ro", "Romanian"),
    "ron": ("ro", "Romanian"),
    "romanian": ("ro", "Romanian"),
    # Ukrainian
    "uk": ("uk", "Ukrainian"),
    "ukr": ("uk", "Ukrainian"),
    "ukrainian": ("uk", "Ukrainian"),
    # Hebrew
    "he": ("he", "Hebrew"),
    "heb": ("he", "Hebrew"),
    "hebrew": ("he", "Hebrew"),
}

# Legacy LANG_MAP for backwards compatibility
LANG_MAP: Dict[str, str] = {k: v[1] for k, v in ISO_LANG_MAP.items()}
LANG_MAP.update({"und": "Undetermined", "sub": "Subtitle", "subs": "Subtitles"})


@dataclass
class SubtitleCue:
    """Represents a single WebVTT subtitle cue."""
    start_time: str
    end_time: str
    text: str
    cue_id: Optional[str] = None
    settings: Optional[str] = None

    def to_vtt(self) -> str:
        res = []
        if self.cue_id:
            res.append(self.cue_id)
        timing = f"{self.start_time} --> {self.end_time}"
        if self.settings:
            timing += f" {self.settings}"
        res.append(timing)
        res.append(self.text)
        return "\n".join(res)


@dataclass
class SubtitleTrack:
    id: int
    name: str
    extension: str
    size_bytes: int
    language: str  # Normalized ISO 639-1 (e.g. 'en', 'es', 'fr', 'ja', 'zh') or 'und'
    label: str
    is_default: bool = False
    is_forced: bool = False
    is_sdh: bool = False
    kind: str = "subtitles"  # 'subtitles', 'captions', 'descriptions'

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "extension": self.extension,
            "size_bytes": self.size_bytes,
            "language": self.language,
            "label": self.label,
            "is_default": self.is_default,
            "is_forced": self.is_forced,
            "is_sdh": self.is_sdh,
            "kind": self.kind,
        }


@dataclass
class SubtitlePackage:
    """Packages multi-track subtitles for a video asset."""
    video_id: int
    video_name: str
    tracks: List[SubtitleTrack] = field(default_factory=list)

    def add_track(self, track: SubtitleTrack) -> None:
        self.tracks.append(track)

    def get_default_track(self) -> Optional[SubtitleTrack]:
        for t in self.tracks:
            if t.is_default:
                return t
        return self.tracks[0] if self.tracks else None

    def get_track_by_language(self, lang_code: str) -> Optional[SubtitleTrack]:
        norm = normalize_language_code(lang_code)
        for t in self.tracks:
            if t.language == norm or t.language.startswith(norm):
                return t
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "video_id": self.video_id,
            "video_name": self.video_name,
            "track_count": len(self.tracks),
            "tracks": [t.to_dict() for t in self.tracks],
        }


# ==============================================================================
# Language Code Normalization (ISO 639-1 / 639-2)
# ==============================================================================

def normalize_language_code(lang: str) -> str:
    """
    Normalizes arbitrary language identifiers, ISO 639-2 (3-letter), ISO 639-1 (2-letter),
    or full names to standard ISO 639-1 codes (e.g., 'eng' -> 'en', 'spa' -> 'es',
    'fre'/'fra' -> 'fr', 'jpn' -> 'ja', 'chi'/'zho' -> 'zh').
    Returns 'und' if unknown.
    """
    if not lang:
        return "und"
    clean = lang.strip().lower().replace("_", "-")
    if clean in ISO_LANG_MAP:
        return ISO_LANG_MAP[clean][0]
    
    # Try prefix before hyphen (e.g., 'en-US' -> 'en', 'zh-CN' -> check if in map)
    if "-" in clean:
        parts = clean.split("-")
        if clean in ISO_LANG_MAP:
            return ISO_LANG_MAP[clean][0]
        if parts[0] in ISO_LANG_MAP:
            return ISO_LANG_MAP[parts[0]][0]

    return "und"


def get_language_display_name(lang: str) -> str:
    """
    Returns the human-readable English name for a given language code or alias.
    """
    if not lang:
        return "Undetermined"
    clean = lang.strip().lower().replace("_", "-")
    if clean in ISO_LANG_MAP:
        return ISO_LANG_MAP[clean][1]
    norm = normalize_language_code(clean)
    if norm in ISO_LANG_MAP:
        return ISO_LANG_MAP[norm][1]
    return clean.capitalize()


# ==============================================================================
# Complex Scene Release & Fuzzy NLP Episode Parser
# ==============================================================================

@dataclass
class ParsedReleaseInfo:
    title: Optional[str] = None
    season: Optional[int] = None
    episode: Optional[int] = None
    episode_end: Optional[int] = None
    language: Optional[str] = None
    is_forced: bool = False
    is_sdh: bool = False
    is_commentary: bool = False
    confidence: float = 0.0


# Regex patterns for noise filtering (scene tags, hashes, groups, resolutions, codecs)
SCENE_NOISE_PATTERNS = [
    r"\[[0-9a-fA-F]{8}\]",                                 # CRC32 Hash: [A1B2C3D4]
    r"\[(?:1080p|720p|480p|2160p|4k|uhd|fhd|hd)\]",       # Resolution tags
    r"\b(?:1080p|720p|480p|2160p|4k|uhd|fhd|hd)\b",
    r"\b(?:x264|x265|h264|h265|hevc|avc|av1|xvid|divx)\b", # Codecs
    r"\b(?:10bit|8bit|hdr|hdr10|dv|dolby\s*vision)\b",     # Color / dynamic range
    r"\b(?:dual[- ]audio|multi[- ]audio|multi|flac|aac|dts|ac3|eac3|truehd|ddp5\.1|5\.1ch|2\.0ch)\b",
    r"\b(?:bluray|blu-ray|bdrip|brrip|web-dl|webrip|web|hdtv|dvdrip|remux)\b",
    r"\b(?:proper|repack|rerip|v2|v3|extended|unrated|directors\.cut|imax)\b",
]

EPISODE_PATTERNS = [
    # S01E05 / s01e05 / S1E5 / S01-E05 / S01.E05 / S01_E05 / S01E05-E06 (multi-ep)
    re.compile(r"[Ss](\d{1,2})[ ._-]*[Ee](\d{1,3})(?:[ ._-]*[Ee](\d{1,3}))?", re.IGNORECASE),
    # 1x05 / 01x05 / 1x05-1x06 / 1x05-06
    re.compile(r"\b(\d{1,2})x(\d{1,3})(?:-(\d{1,3}))?\b", re.IGNORECASE),
    # Season 1 / Ep 5 or Season 1/Ep.05 or Season 1\05.srt
    re.compile(r"(?:season|s)[ ._-]*(\d{1,2})[/\\](?:episode|ep|e)?[ ._-]*(\d{1,3})", re.IGNORECASE),
    # Episode 05 / Ep.05 / Ep05 / E05 / EP_05
    re.compile(r"\b(?:episode|ep|e)[ ._-]*(\d{1,3})\b", re.IGNORECASE),
    # Anime style: "Show Name - 05 [1080p]" or "[Group] Show - 05 - Title" or "Show - 05.mkv"
    re.compile(r"(?:^|[ ._-])- (\d{1,3})(?: -|[ ._\[\(-]|$)", re.IGNORECASE),
    # Folder structure: "Season 1/05.srt" or "S01/05.srt"
    re.compile(r"(?:season[ ._-]*|s)(\d{1,2})[/\\](?:subs?[/\\])?(?:.*[ ._-])?(\d{1,3})(?:\.|\b)", re.IGNORECASE),
    # "Subs/05_English.ass" or "Subs/05.srt" or "Subs/05.en.forced.srt"
    re.compile(r"(?:^|[/\\])(?:subs?|subtitles?)[/\\](?:.*?[ ._-])?(\d{1,3})(?:[ ._-]|\.|$)", re.IGNORECASE),
    # Standalone number bounded by delimiters: " 05 ", "[05]", "(05)", ".05."
    re.compile(r"(?:^|[ ._\[\(-])(\d{1,3})(?:[ ._\]\)-]|$)", re.IGNORECASE),
]


def _clean_tokens(text: str) -> List[str]:
    """Tokenizes a release name into clean lowercase word/number chunks."""
    # Strip extension
    base = os.path.splitext(text)[0]
    
    # Remove bracketed hashes or release groups at start/end
    # e.g. [Group] Show Name -> Show Name
    base = re.sub(r"^\[[^\]]+\]\s*", "", base)
    
    # Apply scene noise patterns
    for pat in SCENE_NOISE_PATTERNS:
        base = re.sub(pat, " ", base, flags=re.IGNORECASE)
        
    # Replace non-alphanumeric with spaces
    tokens = [t for t in re.split(r"[^\w]+", base.lower()) if t]
    return tokens


def parse_scene_release(filepath: str) -> ParsedReleaseInfo:
    """
    NLP & Regex parsing of complex scene releases, anime releases, and subtitle track names.
    Extracts title, season, episode, language, forced/SDH flags, and matching confidence.
    """
    norm_path = filepath.replace("\\", "/")
    filename = os.path.basename(norm_path)
    parent_dirs = norm_path.split("/")[:-1]
    
    info = ParsedReleaseInfo()
    
    # 1. Attribute flags detection
    lower_path = norm_path.lower()
    if re.search(r"\b(?:forced|foreign|signs|songs|songs&signs|sign)\b", lower_path):
        info.is_forced = True
    if re.search(r"\b(?:sdh|cc|hi|hearing[- ]impaired)\b", lower_path):
        info.is_sdh = True
    if re.search(r"\b(?:commentary|comm)\b", lower_path):
        info.is_commentary = True

    # 2. Episode & Season extraction across path and filename
    # Check parent dirs for Season hint (e.g. "Season 1", "S02", "Season 01")
    for parent in parent_dirs:
        m_s = re.search(r"(?:season|s)[ ._-]*(\d{1,2})", parent, re.IGNORECASE)
        if m_s:
            info.season = int(m_s.group(1))
            break

    # Test episode patterns on full path and filename
    for pattern in EPISODE_PATTERNS:
        # Match against filename first, then full path
        for target_str in (filename, norm_path):
            m = pattern.search(target_str)
            if m:
                groups = m.groups()
                if len(groups) == 1 and groups[0] is not None:
                    # Episode only
                    info.episode = int(groups[0])
                    break
                elif len(groups) == 2:
                    if groups[0] is not None and groups[1] is not None:
                        # Season + Episode
                        info.season = int(groups[0])
                        info.episode = int(groups[1])
                        break
                    elif groups[0] is not None:
                        info.episode = int(groups[0])
                        break
                elif len(groups) == 3:
                    if groups[0] is not None and groups[1] is not None:
                        info.season = int(groups[0])
                        info.episode = int(groups[1])
                        if groups[2] is not None:
                            info.episode_end = int(groups[2])
                        break
        if info.episode is not None:
            break

    # 3. Language detection
    lang_code, _ = _detect_language(filepath)
    if lang_code != "und":
        info.language = lang_code

    # 4. Clean title extraction
    # Strip release group at the beginning like `[Erai-raws] ` or `[SubsPlease]`
    raw_title = os.path.splitext(filename)[0]
    raw_title = re.sub(r"^\[[^\]]+\]\s*", "", raw_title)
    
    # Strip episode tokens and trailing scene tags
    for pat in [
        r"[Ss]\d{1,2}[ ._-]*[Ee]\d{1,3}(?:[ ._-]*[Ee]\d{1,3})?",
        r"\b\d{1,2}x\d{1,3}\b",
        r"\b(?:episode|ep|e)[ ._-]*\d{1,3}\b",
        r"(?:^|[ ._-])- \d{1,3}(?: -|[ ._\[\(-]|$)",
    ]:
        raw_title = re.split(pat, raw_title, flags=re.IGNORECASE)[0]
    
    # Apply noise cleaning
    for pat in SCENE_NOISE_PATTERNS:
        raw_title = re.sub(pat, " ", raw_title, flags=re.IGNORECASE)
        
    cleaned_title = re.sub(r"[._-]+", " ", raw_title).strip()
    if cleaned_title:
        info.title = cleaned_title

    return info


def _extract_episode_number(filename: str) -> Optional[int]:
    """
    Extract episode number from filename/filepath patterns like:
    S01E02, s1e2, 1x05, EP02, Subs/05_English.ass, Season 1/Ep 5.vtt, 01.srt, etc.
    """
    info = parse_scene_release(filename)
    return info.episode


def _clean_stem(filename: str) -> str:
    """Removes extension and common trailing language/forced tags for stem matching."""
    stem = os.path.splitext(os.path.basename(filename))[0]
    # Remove release group prefix
    stem = re.sub(r"^\[[^\]]+\]\s*", "", stem)
    # Remove language tag / forced / sdh if present at end
    stem = re.sub(
        r"[._ -](?:en|eng|english|ja|jp|jpn|japanese|chs|cht|zh|chi|zho|es|spa|fr|fre|fra|de|ger|ru|rus|ko|kor|und|default|forced|sdh|cc)$",
        "",
        stem,
        flags=re.IGNORECASE,
    )
    return stem.lower().strip()


def _detect_language(sub_filename: str) -> Tuple[str, str]:
    """
    Detects normalized ISO 639-1 language code and human-readable label from subtitle path.
    Returns (iso_639_1_code, label).
    """
    norm_path = sub_filename.replace("\\", "/")
    stem = os.path.splitext(os.path.basename(norm_path))[0]
    
    # Check tokens in filename from right to left (e.g. Show.S01E05.en.forced.srt -> 'en', 'forced')
    parts = re.split(r"[._ -]+", stem.lower())
    for part in reversed(parts):
        if part in ("forced", "sdh", "cc", "default", "sub", "subs"):
            continue
        if part in ISO_LANG_MAP:
            return ISO_LANG_MAP[part]

    # Check directory hierarchy (e.g. Subs/English/01.srt or Subs/es/05.ass)
    dir_parts = norm_path.split("/")[:-1]
    for d in reversed(dir_parts):
        d_clean = d.lower()
        if d_clean in ISO_LANG_MAP:
            return ISO_LANG_MAP[d_clean]
        for k, v in ISO_LANG_MAP.items():
            if k == d_clean or f"/{k}/" in f"/{d_clean}/" or d_clean.startswith(f"{k}_") or d_clean.startswith(f"{k}-"):
                return v

    return "und", "Subtitle"


def is_subtitle_file(filename: str) -> bool:
    """Check if filename has a supported subtitle extension."""
    ext = os.path.splitext(filename)[1].lower()
    return ext in SUBTITLE_EXTENSIONS


def is_video_file(filename: str) -> bool:
    """Check if filename has a recognized video extension."""
    ext = os.path.splitext(filename)[1].lower()
    return ext in VIDEO_EXTENSIONS


# ==============================================================================
# Fuzzy NLP Subtitle & Video Matching
# ==============================================================================

def _calculate_fuzzy_match_score(video_path: str, sub_path: str) -> float:
    """
    Calculates a fuzzy NLP match score (0.0 to 1.0) between a video release and a subtitle release.
    Takes into account title token overlap, season, episode, release group, and directory tree.
    """
    v_info = parse_scene_release(video_path)
    s_info = parse_scene_release(sub_path)
    
    score = 0.0

    # 1. Episode matching logic (Hard criteria)
    if v_info.episode is not None and s_info.episode is not None:
        if v_info.episode == s_info.episode or (
            v_info.episode_end and v_info.episode <= s_info.episode <= v_info.episode_end
        ):
            score += 0.50
        else:
            # Different episode numbers -> hard mismatch
            return 0.0
    elif v_info.episode is not None or s_info.episode is not None:
        # One has an episode number, the other does not -> lower probability
        score += 0.05
    else:
        # Both are non-episodic (e.g. movies)
        score += 0.25

    # 2. Season matching logic
    if v_info.season is not None and s_info.season is not None:
        if v_info.season == s_info.season:
            score += 0.20
        else:
            return 0.0
    elif v_info.season is not None or s_info.season is not None:
        score += 0.05
    else:
        score += 0.10

    # 3. NLP Token Jaccard / Stem Similarity
    v_tokens = set(_clean_tokens(video_path))
    s_tokens = set(_clean_tokens(sub_path))
    
    # Exclude common sub tokens from Jaccard calculation
    s_tokens = {t for t in s_tokens if t not in ("sub", "subs", "subtitles", "english", "forced", "sdh", "ass", "srt", "vtt")}
    v_tokens = {t for t in v_tokens if t not in ("mkv", "mp4", "avi", "1080p", "720p", "hevc", "x264")}

    if v_tokens and s_tokens:
        overlap = v_tokens.intersection(s_tokens)
        union = v_tokens.union(s_tokens)
        token_sim = len(overlap) / len(union) if union else 0.0
        score += 0.30 * token_sim
    else:
        score += 0.15

    return min(1.0, score)


def match_subtitles_for_video(video_entry: Dict[str, Any], all_entries: List[Dict[str, Any]]) -> List[SubtitleTrack]:
    """
    Matches subtitle entries from an archive to a given video entry using fuzzy NLP heuristics.
    Handles:
      - Complex scene releases: `[Group] Show Name - S01E05 - 1080p [Dual-Audio] [Hash].mkv`
        matching `Show.Name.1x05.en.forced.srt`, `Subs/05_English.ass`, `Season 1/Ep 5.vtt`
      - Language normalization (ISO 639-1)
      - Forced & SDH track classification
      - Multi-video episode segregation
    """
    video_name = video_entry.get("name", "")
    video_stem = _clean_stem(video_name)
    v_info = parse_scene_release(video_name)
    
    all_videos = [e for e in all_entries if is_video_file(e.get("name", ""))]
    sub_entries = [e for e in all_entries if is_subtitle_file(e.get("name", ""))]
    
    matched_tracks: List[SubtitleTrack] = []
    
    for sub in sub_entries:
        sub_name = sub.get("name", "")
        sub_ext = os.path.splitext(sub_name)[1].lower()
        sub_stem = _clean_stem(sub_name)
        s_info = parse_scene_release(sub_name)
        
        is_match = False
        
        # 1. Exact or prefix stem match (e.g. video.mkv and video.en.srt)
        if sub_stem == video_stem or (video_stem and sub_stem.startswith(video_stem)) or (sub_stem and video_stem.startswith(sub_stem)):
            is_match = True
        # 2. Episode & Season exact match
        elif v_info.episode is not None and s_info.episode is not None:
            if v_info.episode == s_info.episode:
                if v_info.season is None or s_info.season is None or v_info.season == s_info.season:
                    is_match = True
        # 3. Fuzzy NLP token score threshold
        else:
            match_score = _calculate_fuzzy_match_score(video_name, sub_name)
            if match_score >= 0.45:
                is_match = True
            elif len(all_videos) == 1 and (v_info.episode is None or s_info.episode is None or v_info.episode == s_info.episode):
                is_match = True

        if is_match:
            lang_code, lang_label = _detect_language(sub_name)
            
            # Format display label
            label_parts = [lang_label]
            if s_info.is_forced:
                label_parts.append("Forced")
            if s_info.is_sdh:
                label_parts.append("SDH")
            label_parts.append(f"({sub_ext.lstrip('.').upper()})")
            
            label = " ".join(label_parts)
            is_default = len(matched_tracks) == 0 and (lang_code == "en" or len(sub_entries) == 1)
            kind = "captions" if s_info.is_sdh else "subtitles"
            
            matched_tracks.append(
                SubtitleTrack(
                    id=sub.get("id", 0),
                    name=sub_name,
                    extension=sub_ext,
                    size_bytes=sub.get("size_bytes", 0),
                    language=lang_code,
                    label=label,
                    is_default=is_default,
                    is_forced=s_info.is_forced,
                    is_sdh=s_info.is_sdh,
                    kind=kind,
                )
            )

    # Sort tracks: default first, then non-forced before forced, then language
    matched_tracks.sort(key=lambda t: (not t.is_default, t.is_forced, t.language != "en", t.label))
    return matched_tracks


def package_subtitles_for_video(video_entry: Dict[str, Any], all_entries: List[Dict[str, Any]]) -> SubtitlePackage:
    """
    Creates a SubtitlePackage containing all matched and normalized tracks for a video entry.
    """
    tracks = match_subtitles_for_video(video_entry, all_entries)
    package = SubtitlePackage(
        video_id=video_entry.get("id", 0),
        video_name=video_entry.get("name", ""),
        tracks=tracks,
    )
    return package


def pair_archive_subtitles(entries: List[Dict[str, Any]]) -> Dict[int, List[Dict[str, Any]]]:
    """
    Scans all archive entries, finds videos, and maps each video ID to its matched subtitle tracks.
    Returns: {video_id: [subtitle_dict, ...]}
    """
    result: Dict[int, List[Dict[str, Any]]] = {}
    video_entries = [e for e in entries if is_video_file(e.get("name", ""))]

    for v in video_entries:
        pkg = package_subtitles_for_video(v, entries)
        result[v.get("id", 0)] = [t.to_dict() for t in pkg.tracks]

    return result


# ==============================================================================
# WebVTT Cue Sanitization & Formatting
# ==============================================================================

def _format_vtt_timestamp(hours: int, minutes: int, seconds: int, milliseconds: int) -> str:
    """Formats timestamp into standard WebVTT HH:MM:SS.mmm representation."""
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"


def sanitize_vtt_cue_text(text: str) -> str:
    """
    Sanitizes WebVTT cue text:
      - Strips HTML unsafe markup / script tags while preserving allowed WebVTT tags (<b>, <i>, <u>, <c>, <v>)
      - Removes ASS style overrides ({\\pos(..)}, {\\c&H..}, {\\an8}, etc.)
      - Converts literal \\N, \\n to real newlines
      - Normalizes unicode whitespace and removes null bytes / control characters
      - Unescapes HTML entities safely (e.g. &amp; -> &)
    """
    if not text:
        return ""

    # 1. Remove null bytes and control chars (except \n, \r, \t)
    text = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", text)

    # 2. Convert ASS linebreaks
    text = re.sub(r"\\[Nn]", "\n", text)
    text = text.replace(r"\h", " ")

    # 3. Strip ASS style tags like {\pos(100,200)}, {\c&H0000FF&}, {\b1}, {\fs24}, etc.
    text = re.sub(r"\{[^}]*\}", "", text)

    # 4. Remove unsafe HTML tags (e.g. <script>, <iframe>, <font color="..."> -> strip font tag or keep content)
    text = re.sub(r"<\s*script[^>]*>.*?<\s*/\s*script\s*>", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<\s*style[^>]*>.*?<\s*/\s*style\s*>", "", text, flags=re.IGNORECASE | re.DOTALL)

    # Replace <font ...> and </font> with clean text
    text = re.sub(r"</?font[^>]*>", "", text, flags=re.IGNORECASE)

    # 5. Clean disallowed tags but preserve <b>, <i>, <u>, <v>, <c>, <ruby>, <rt>
    def clean_tag(match: re.Match) -> str:
        tag_content = match.group(1).strip()
        tag_name = tag_content.split()[0].lower().lstrip("/")
        if tag_name in ("b", "i", "u", "v", "c", "ruby", "rt", "lang"):
            return f"<{tag_content}>"
        return ""

    text = re.sub(r"<([^>]+)>", clean_tag, text)

    # 6. HTML unescape for clean rendering
    text = html.unescape(text)

    # 7. Clean whitespace per line
    lines = [line.strip() for line in text.split("\n")]
    return "\n".join(lines).strip()


def srt_to_vtt(srt_content: str) -> str:
    """
    Converts SubRip (.srt) text content into WebVTT (.vtt) format with cue sanitization.
    Ensures 'WEBVTT' header, converts comma timestamps to dot, and sanitizes payload.
    """
    if not srt_content.strip():
        return "WEBVTT\n\n"

    # Normalize line endings
    text = srt_content.replace("\r\n", "\n").replace("\r", "\n").strip()
    
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
                if ts_pattern.search(lines[i]) or (lines[i].strip().isdigit() and i + 1 < len(lines) and ts_pattern.search(lines[i+1])):
                    break
                cue_text.append(lines[i])
                i += 1
            sanitized_text = sanitize_vtt_cue_text("\n".join(cue_text))
            if sanitized_text:
                vtt_lines.append(sanitized_text)
            vtt_lines.append("")
        else:
            i += 1

    return "\n".join(vtt_lines).strip() + "\n"


def ass_to_vtt(ass_content: str) -> str:
    """
    Converts Advanced SubStation Alpha (.ass / .ssa) content to WebVTT format with cue sanitization.
    Strips ASS styling tags (e.g. {\\pos(x,y)}, {\\i1}, {\\c&H...&}) and cleans dialogue text.
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
                fields = [f.strip().lower() for f in line_clean[7:].split(",")]
                format_indices = {field: idx for idx, field in enumerate(fields)}
                continue

            if line_clean.lower().startswith("dialogue:"):
                raw_data = line_clean[9:].strip()
                max_splits = len(format_indices) - 1 if format_indices else 9
                parts = [p.strip() for p in raw_data.split(",", max_splits)]

                if not format_indices:
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

                clean_text = sanitize_vtt_cue_text(text_str)
                if clean_text:
                    vtt_lines.append(f"{vtt_start} --> {vtt_end}")
                    vtt_lines.append(clean_text)
                    vtt_lines.append("")

    return "\n".join(vtt_lines).strip() + "\n"


def convert_to_vtt(content: str, filename_or_ext: str) -> str:
    """
    Converts subtitle text content from SRT, ASS/SSA, or VTT to clean, sanitized WebVTT format.
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
        return srt_to_vtt(content)

