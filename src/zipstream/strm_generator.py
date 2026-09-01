"""
ZipStreamHub STRM Virtual Media Library Generator
Generates .strm files and bundled in-memory ZIP structures for Jellyfin, Emby, and Kodi.
Enables instant zero-download direct streaming from remote ZIP/ZIP64 archives.
"""

from __future__ import annotations

import io
import os
import posixpath
import re
import urllib.parse
import zipfile
from typing import Any, Dict, List, Optional, Tuple

try:
    from .subtitle_parser import is_video_file
except ImportError:
    from subtitle_parser import is_video_file


def generate_strm_content(stream_url: str) -> str:
    """
    Generates the text content of a standard .strm file.
    Jellyfin, Emby, and Kodi read the single URL line (with trailing newline) from .strm files.
    """
    cleaned_url = stream_url.strip()
    return f"{cleaned_url}\n"


def parse_media_structure(filename: str) -> Tuple[Optional[str], Optional[int], Optional[int], str]:
    """
    Extracts show/movie name, season number, episode number, and clean base title from a filename/path.
    Returns:
        (show_name, season_num, episode_num, clean_title)
    
    Examples:
        - "Breaking.Bad.S01E02.1080p.mkv" -> ("Breaking Bad", 1, 2, "Breaking Bad S01E02")
        - "Shows/Severance/Season 2/Severance.S02E05.mkv" -> ("Severance", 2, 5, "Severance S02E05")
        - "Inception.2010.1080p.mkv" -> ("Inception (2010)", None, None, "Inception (2010)")
    """
    # Normalize path separators
    norm_path = filename.replace("\\", "/")
    path_parts = [p for p in norm_path.split("/") if p]
    file_name = path_parts[-1]
    name_no_ext = os.path.splitext(file_name)[0]

    # Check for SxxExx pattern (e.g. S01E02, s01.e02, S1E2, Season 1 Episode 2)
    s_e_match = re.search(r"^(.*?)[ ._-]*[Ss](\d{1,2})[ ._x-]*[Ee](\d{1,3})(.*)$", name_no_ext, re.IGNORECASE)
    if s_e_match:
        raw_show = s_e_match.group(1).strip(" ._-")
        season_num = int(s_e_match.group(2))
        episode_num = int(s_e_match.group(3))
        
        # If show name in filename is empty or generic, check parent directory
        if not raw_show and len(path_parts) > 1:
            for parent in reversed(path_parts[:-1]):
                if not re.match(r"^Season[ ._-]*\d+$", parent, re.IGNORECASE) and not re.match(r"^Specials?$", parent, re.IGNORECASE):
                    raw_show = parent
                    break
        
        # Format show name cleanly
        show_title = _clean_name(raw_show) if raw_show else "Show"
        clean_title = f"{show_title} S{season_num:02d}E{episode_num:02d}"
        return (show_title, season_num, episode_num, clean_title)

    # Check for Season folder hierarchy: e.g. "Game of Thrones/Season 1/01.mkv" or "Show/Season 01/Ep 01.mkv"
    season_dir_match = None
    show_dir = None
    if len(path_parts) >= 2:
        for idx, part in enumerate(path_parts[:-1]):
            m = re.search(r"^Season[ ._-]*(\d{1,2})$", part, re.IGNORECASE)
            if m:
                season_dir_match = int(m.group(1))
                if idx > 0:
                    show_dir = path_parts[idx - 1]
                break

    # Check for episode pattern in filename (e.g. "EP01", "Episode 01", "01 - Pilot", "01")
    ep_match = re.search(r"(?:ep|episode)?[ ._#-]*(\d{1,3})", name_no_ext, re.IGNORECASE)
    if season_dir_match is not None and ep_match:
        episode_num = int(ep_match.group(1))
        show_title = _clean_name(show_dir) if show_dir else "Show"
        clean_title = f"{show_title} S{season_dir_match:02d}E{episode_num:02d}"
        return (show_title, season_dir_match, episode_num, clean_title)

    # Check for movie year pattern: e.g. "Interstellar.2014.1080p.mkv" or "The Matrix (1999).mp4"
    year_match = re.search(r"^(.*?)[ ._\-\(]((?:19|20)\d{2})[ ._\-\)]*(.*)$", name_no_ext)
    if year_match:
        raw_movie = year_match.group(1).strip(" ._-")
        year = year_match.group(2)
        movie_title = _clean_name(raw_movie) if raw_movie else "Movie"
        clean_title = f"{movie_title} ({year})"
        return (None, None, None, clean_title)

    # Fallback to cleaned filename
    clean_title = _clean_name(name_no_ext)
    return (None, None, None, clean_title)


def _clean_name(name: str) -> str:
    """Replaces dots, underscores, and common release tags with clean spaces."""
    cleaned = re.sub(r"[._]+", " ", name)
    # Remove resolution / codec tags if dangling at end
    cleaned = re.sub(r"\b(1080p|720p|2160p|4k|uhd|bluray|web-dl|webrip|h264|h265|x264|x265|hevc|aac|dts)\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def generate_strm_path(entry_name: str, structure_type: str = "auto") -> str:
    """
    Computes standard directory hierarchy path for .strm file.
    
    Standard structures supported:
    - TV Show: `{Show Name}/Season {XX}/{Show Name} S{XX}E{YY}.strm`
    - Movie: `{Movie Name} ({Year})/{Movie Name} ({Year}).strm` or `{Movie Name}.strm`
    - Direct: Matches original folder structure inside zip with extension replaced by `.strm`
    """
    show_name, season_num, ep_num, clean_title = parse_media_structure(entry_name)

    if structure_type == "auto":
        if show_name and season_num is not None and ep_num is not None:
            # Jellyfin / Emby / Kodi standard TV library layout
            season_str = f"Season {season_num:02d}"
            file_name = f"{show_name} S{season_num:02d}E{ep_num:02d}.strm"
            return posixpath.join(show_name, season_str, file_name)
        elif not show_name and "(" in clean_title and ")" in clean_title:
            # Movie with year folder structure (Jellyfin/Emby recommendation)
            return posixpath.join(clean_title, f"{clean_title}.strm")
        else:
            # Mirror zip structure but with .strm extension
            norm = entry_name.replace("\\", "/")
            base_no_ext = os.path.splitext(norm)[0]
            return f"{base_no_ext}.strm"

    elif structure_type == "flat":
        base_name = os.path.splitext(os.path.basename(entry_name.replace("\\", "/")))[0]
        return f"{base_name}.strm"

    else:
        norm = entry_name.replace("\\", "/")
        base_no_ext = os.path.splitext(norm)[0]
        return f"{base_no_ext}.strm"


def generate_strm_zip_bundle(
    entries: List[Dict[str, Any]],
    base_stream_url: str,
    structure_type: str = "auto"
) -> bytes:
    """
    Bundles individual .strm files into an in-memory ZIP package organized by
    Season/Show directory structure so users can extract directly into
    Jellyfin, Emby, or Kodi media library folders.

    Args:
        entries: List of archive file entries (each having at least 'id' and 'name').
        base_stream_url: Base URL of the ZipStreamHub server (e.g. 'http://127.0.0.1:8787' or 'http://192.168.1.100:8787').
        structure_type: 'auto' (default standard media server structure), 'flat', or 'mirror'.

    Returns:
        bytes: Binary ZIP package content.
    """
    base_url = base_stream_url.rstrip("/")
    
    # Filter to video files if entries contains non-video files; fallback to all if no video extensions match
    video_entries = [e for e in entries if is_video_file(e.get("name", ""))]
    if not video_entries and entries:
        video_entries = entries

    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for ep in sorted(video_entries, key=lambda x: x.get("id", 0)):
            ep_id = ep.get("id", 0)
            orig_name = ep.get("name", f"video_{ep_id}.mkv")
            
            # Construct standard stream endpoint URL
            encoded_name = urllib.parse.quote(orig_name)
            stream_url = f"{base_url}/stream/{ep_id}/{encoded_name}"
            strm_data = generate_strm_content(stream_url)
            
            strm_path = generate_strm_path(orig_name, structure_type=structure_type)
            zf.writestr(strm_path, strm_data.encode("utf-8"))

    zip_buffer.seek(0)
    return zip_buffer.getvalue()
