#!/usr/bin/env python3
"""
ZipStreamHub CLI Interactive Stream Player & Suite Controller
- Clean ASCII/ANSI layout with archive overview (size, count, STORE vs DEFLATE stats)
- Formatted video entries table with codec, resolution, size, and duration
- Interactive commands:
    p <id>   : Play in detected player (PotPlayer / VLC / MPV / MPC-HC / MPC-BE / IINA)
    w <id>   : Open in Web Browser
    m3u      : Export M3U playlist file
    strm     : Export STRM ZIP bundle
    stats    : View active streaming throughput & bandwidth metrics
    q / exit : Quit
- Non-interactive CLI flags:
    --play / --ep <id> : Play specified episode directly
    --player <name>    : Target player (e.g. potplayer, vlc, mpv, mpc-hc, browser)
    --export-m3u <out> : Export M3U playlist to file
    --export-strm <out>: Export STRM ZIP bundle to file
    --list             : Print video entries table and exit
    --port <port>      : Custom local server port (default: 8787)
"""

import argparse
import io
import os
import sys
import time
import shutil
import subprocess
import threading
import urllib.parse
from typing import List, Dict, Optional, Any, Tuple

# Ensure ANSI escape sequences are supported on Windows
if sys.platform == "win32":
    os.system("")

# Ensure UTF-8 output
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


# ANSI Color & Style Codes
class Style:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"
    UNDERLINE = "\033[4m"
    
    # Foreground colors
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    
    # Bright foreground colors
    BRIGHT_BLACK = "\033[90m"
    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"
    BRIGHT_WHITE = "\033[97m"
    
    # Background colors
    BG_BLUE = "\033[44m"
    BG_CYAN = "\033[46m"
    BG_MAGENTA = "\033[45m"
    BG_DARK = "\033[100m"


def format_bytes(size: int) -> str:
    """Format byte count into human-readable representation."""
    if size >= 1024 ** 4:
        return f"{size / (1024 ** 4):.2f} TB"
    elif size >= 1024 ** 3:
        return f"{size / (1024 ** 3):.2f} GB"
    elif size >= 1024 ** 2:
        return f"{size / (1024 ** 2):.1f} MB"
    elif size >= 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size} B"


def format_duration(seconds: Optional[float]) -> str:
    """Format seconds into HH:MM:SS or MM:SS."""
    if seconds is None or seconds <= 0:
        return "--:--"
    total_secs = int(round(seconds))
    hrs = total_secs // 3600
    mins = (total_secs % 3600) // 60
    secs = total_secs % 60
    if hrs > 0:
        return f"{hrs:02d}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"


def print_banner():
    banner = f"""
{Style.BRIGHT_CYAN}{Style.BOLD}================================================================================{Style.RESET}
{Style.BRIGHT_YELLOW}{Style.BOLD}           ⚡  ZipStreamHub — High-Speed Remote ZIP Player  ⚡{Style.RESET}
{Style.BRIGHT_CYAN}      Instant HTTP Range Seeking | Zero-Disk Extraction | Multi-Player Stream{Style.RESET}
{Style.BRIGHT_CYAN}{Style.BOLD}================================================================================{Style.RESET}"""
    print(banner)


def import_components():
    """Dynamically loads and initializes core engine, server, inspector, and player components."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from engine import RemoteZipReader, StreamPrefetcher, HTTP_POOL, METRICS, get_streaming_metrics
    from server import ZipStreamWebHandler, ThreadedZipStreamServer, ARCHIVE_LOCK, PORT
    from player_detector import get_installed_players, launch_stream
    from media_inspector import inspect_media_header
    from strm_generator import generate_strm_zip_bundle
    from subtitle_parser import is_video_file
    return {
        "RemoteZipReader": RemoteZipReader,
        "StreamPrefetcher": StreamPrefetcher,
        "HTTP_POOL": HTTP_POOL,
        "METRICS": METRICS,
        "get_streaming_metrics": get_streaming_metrics,
        "ZipStreamWebHandler": ZipStreamWebHandler,
        "ThreadedZipStreamServer": ThreadedZipStreamServer,
        "ARCHIVE_LOCK": ARCHIVE_LOCK,
        "PORT": PORT,
        "get_installed_players": get_installed_players,
        "launch_stream": launch_stream,
        "inspect_media_header": inspect_media_header,
        "generate_strm_zip_bundle": generate_strm_zip_bundle,
        "is_video_file": is_video_file,
    }


class CLIStreamingServer:
    """Manages background HTTP server for CLI streaming playback."""
    def __init__(self, port: int = 8787):
        self.port = port
        self.server: Optional[Any] = None
        self.thread: Optional[threading.Thread] = None
        self.is_running = False

    def start(self, reader: Any):
        if self.is_running:
            self.update_reader(reader)
            return

        comps = import_components()
        ThreadedServer = comps["ThreadedZipStreamServer"]
        Handler = comps["ZipStreamWebHandler"]
        ARCHIVE_LOCK = comps["ARCHIVE_LOCK"]

        # Register reader into server globals
        import server as server_mod
        with ARCHIVE_LOCK:
            server_mod.CURRENT_READER = reader
            server_mod.CACHED_ENTRIES = {e["id"]: e for e in reader.entries}
            server_mod.READERS_BY_URL[reader.url] = reader

        try:
            self.server = ThreadedServer(("127.0.0.1", self.port), Handler)
        except OSError:
            # Fallback if port already in use
            self.server = ThreadedServer(("127.0.0.1", 0), Handler)
            self.port = self.server.server_address[1]

        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.is_running = True

    def update_reader(self, reader: Any):
        comps = import_components()
        ARCHIVE_LOCK = comps["ARCHIVE_LOCK"]
        import server as server_mod
        with ARCHIVE_LOCK:
            server_mod.CURRENT_READER = reader
            server_mod.CACHED_ENTRIES = {e["id"]: e for e in reader.entries}
            server_mod.READERS_BY_URL[reader.url] = reader

    def stop(self):
        if self.server:
            try:
                self.server.shutdown()
                self.server.server_close()
            except Exception:
                pass
            self.is_running = False


def print_archive_overview(reader: Any):
    """
    Renders clean ASCII / ANSI archive overview box:
    - Total Size & File count
    - STORE (0-CPU direct seek) vs DEFLATE stats
    - Detected Players
    """
    total_size = reader.total_size
    entries = reader.entries
    comps = import_components()
    is_video_file = comps["is_video_file"]
    get_installed_players = comps["get_installed_players"]

    store_count = sum(1 for e in entries if e.get("method", 0) == 0)
    deflate_count = sum(1 for e in entries if e.get("method", 0) == 8)
    other_count = len(entries) - store_count - deflate_count
    
    video_entries = [e for e in entries if is_video_file(e.get("name", ""))]
    video_count = len(video_entries)
    
    store_pct = (store_count / len(entries) * 100) if entries else 0.0
    deflate_pct = (deflate_count / len(entries) * 100) if entries else 0.0

    detected_players = get_installed_players()
    player_names = [v["name"] for k, v in detected_players.items() if k != "browser"]
    players_str = ", ".join(player_names) if player_names else "Web Browser Only"

    print(f"\n{Style.BRIGHT_BLUE}┌─── {Style.BOLD}{Style.BRIGHT_WHITE}ARCHIVE OVERVIEW{Style.RESET}{Style.BRIGHT_BLUE} " + "─" * 58 + f"┐{Style.RESET}")
    print(f"{Style.BRIGHT_BLUE}│{Style.RESET}  {Style.BOLD}Total Size  :{Style.RESET} {Style.BRIGHT_YELLOW}{format_bytes(total_size):<14}{Style.RESET} │  {Style.BOLD}Total Files :{Style.RESET} {Style.BRIGHT_WHITE}{len(entries)} items ({video_count} videos){Style.RESET}")
    print(f"{Style.BRIGHT_BLUE}│{Style.RESET}  {Style.BOLD}Compression :{Style.RESET} {Style.BRIGHT_GREEN}STORE: {store_count} ({store_pct:.1f}%){Style.RESET} | {Style.BRIGHT_MAGENTA}DEFLATE: {deflate_count} ({deflate_pct:.1f}%){Style.RESET}" + (f" | {other_count} other" if other_count else ""))
    print(f"{Style.BRIGHT_BLUE}│{Style.RESET}  {Style.BOLD}Players     :{Style.RESET} {Style.BRIGHT_CYAN}{players_str}{Style.RESET}")
    print(f"{Style.BRIGHT_BLUE}└───" + "─" * 74 + f"┘{Style.RESET}")


def get_entry_media_info(reader: Any, entry: Dict[str, Any], inspect_cache: Dict[int, Dict[str, Any]]) -> Dict[str, Any]:
    """Retrieves or inspects video codec, resolution, and duration."""
    entry_id = entry.get("id", 0)
    if entry_id in inspect_cache:
        return inspect_cache[entry_id]

    comps = import_components()
    inspect_fn = comps["inspect_media_header"]
    try:
        info = inspect_fn(reader, entry, initial_bytes=65536)
    except Exception:
        info = {"video_codec": None, "width": None, "height": None, "duration_sec": None}
    
    inspect_cache[entry_id] = info
    return info


def print_video_table(reader: Any, inspect_cache: Dict[int, Dict[str, Any]], probe_limit: int = 20):
    """
    Renders video entries in a formatted, aligned ASCII table with codec, resolution, size, and duration.
    """
    comps = import_components()
    is_video_file = comps["is_video_file"]
    
    entries = reader.entries
    video_entries = [e for e in entries if is_video_file(e.get("name", ""))]
    if not video_entries:
        video_entries = entries  # Fallback to all if no video extensions matched

    print(f"\n{Style.BRIGHT_CYAN}┌────┬─────────┬────────────┬─────────────┬───────────┬──────────────────────────────────────────┐{Style.RESET}")
    print(f"{Style.BRIGHT_CYAN}│{Style.BOLD}{Style.BRIGHT_WHITE} ID {Style.RESET}{Style.BRIGHT_CYAN}│{Style.BOLD}{Style.BRIGHT_WHITE}  SIZE   {Style.RESET}{Style.BRIGHT_CYAN}│{Style.BOLD}{Style.BRIGHT_WHITE}   CODEC    {Style.RESET}{Style.BRIGHT_CYAN}│{Style.BOLD}{Style.BRIGHT_WHITE} RESOLUTION  {Style.RESET}{Style.BRIGHT_CYAN}│{Style.BOLD}{Style.BRIGHT_WHITE} DURATION  {Style.RESET}{Style.BRIGHT_CYAN}│{Style.BOLD}{Style.BRIGHT_WHITE} FILENAME                                 {Style.RESET}{Style.BRIGHT_CYAN}│{Style.RESET}")
    print(f"{Style.BRIGHT_CYAN}├────┼─────────┼────────────┼─────────────┼───────────┼──────────────────────────────────────────┤{Style.RESET}")

    for idx, e in enumerate(video_entries):
        eid = e.get("id", idx + 1)
        size_bytes = e.get("size_bytes") or int(e.get("size_gb", 0) * (1024 ** 3))
        size_str = format_bytes(size_bytes)
        name = os.path.basename(e.get("name", f"file_{eid}").replace("\\", "/"))

        # Inspect media metadata (for first N entries or on-demand)
        if idx < probe_limit:
            info = get_entry_media_info(reader, e, inspect_cache)
            codec = info.get("video_codec") or ("STORE" if e.get("method", 0) == 0 else "DEFLATE")
            w = info.get("width")
            h = info.get("height")
            if w and h:
                res = f"{w}x{h}"
                if h == 2160 or w == 3840:
                    res = "4K 2160p"
                elif h == 1080:
                    res = "1080p FHD"
                elif h == 720:
                    res = "720p HD"
            else:
                res = "Direct"
            duration = format_duration(info.get("duration_sec"))
        else:
            codec = "STORE" if e.get("method", 0) == 0 else "DEFLATE"
            res = "Auto"
            duration = "--:--"

        # Truncate filename if needed
        max_name_len = 40
        disp_name = name if len(name) <= max_name_len else name[:max_name_len - 3] + "..."
        
        # Method color
        is_store = e.get("method", 0) == 0
        method_style = Style.BRIGHT_GREEN if is_store else Style.BRIGHT_MAGENTA

        print(f"{Style.BRIGHT_CYAN}│{Style.RESET}{Style.BOLD}{eid:>3} {Style.RESET}{Style.BRIGHT_CYAN}│{Style.RESET} {size_str:>7} {Style.BRIGHT_CYAN}│{Style.RESET} {method_style}{codec:<10}{Style.RESET} {Style.BRIGHT_CYAN}│{Style.RESET} {Style.BRIGHT_YELLOW}{res:<11}{Style.RESET} {Style.BRIGHT_CYAN}│{Style.RESET} {Style.DIM}{duration:<9}{Style.RESET} {Style.BRIGHT_CYAN}│{Style.RESET} {Style.BRIGHT_WHITE}{disp_name:<40}{Style.RESET} {Style.BRIGHT_CYAN}│{Style.RESET}")

    if len(video_entries) > probe_limit:
        remaining = len(video_entries) - probe_limit
        print(f"{Style.BRIGHT_CYAN}│{Style.DIM} ... and {remaining} more items. (Use ID to select and play any item)                        {Style.RESET}{Style.BRIGHT_CYAN}│{Style.RESET}")

    print(f"{Style.BRIGHT_CYAN}└────┴─────────┴────────────┴─────────────┴───────────┴──────────────────────────────────────────┘{Style.RESET}")


def export_m3u_playlist(reader: Any, output_path: str, base_url: str = "http://127.0.0.1:8787") -> str:
    """Generates and writes an M3U IPTV playlist file."""
    comps = import_components()
    is_video_file = comps["is_video_file"]
    
    video_entries = [e for e in reader.entries if is_video_file(e.get("name", ""))]
    if not video_entries:
        video_entries = reader.entries

    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:3",
        f"# PLAYLIST GENERATED BY ZIPSTREAM HUB ({len(video_entries)} items)"
    ]
    for ep in sorted(video_entries, key=lambda x: x["id"]):
        name = ep.get("name", f"Track {ep['id']}")
        encoded_name = urllib.parse.quote(name)
        stream_link = f"{base_url.rstrip('/')}/stream/{ep['id']}/{encoded_name}"
        lines.append(f'#EXTINF:-1 tvg-name="{name}" group-title="ZipStream Hub",{name}')
        lines.append(stream_link)

    content = "\n".join(lines) + "\n"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)
    return output_path


def export_strm_bundle(reader: Any, output_path: str, base_url: str = "http://127.0.0.1:8787") -> str:
    """Generates and writes a STRM ZIP bundle file."""
    comps = import_components()
    generate_strm_zip_bundle = comps["generate_strm_zip_bundle"]
    
    zip_bytes = generate_strm_zip_bundle(reader.entries, base_url, structure_type="auto")
    with open(output_path, "wb") as f:
        f.write(zip_bytes)
    return output_path


def print_active_stats():
    """Displays active streaming throughput and bandwidth metrics."""
    comps = import_components()
    get_metrics = comps["get_streaming_metrics"]
    stats = get_metrics()

    mbps = stats.get("bandwidth_mbps", 0.0)
    total_bytes = stats.get("total_bytes_served", 0)
    active_count = stats.get("active_streams", 0)
    throttle = stats.get("throttle_mbps")

    print(f"\n{Style.BRIGHT_GREEN}┌─── {Style.BOLD}{Style.BRIGHT_WHITE}STREAMING THROUGHPUT STATS{Style.RESET}{Style.BRIGHT_GREEN} " + "─" * 48 + f"┐{Style.RESET}")
    print(f"{Style.BRIGHT_GREEN}│{Style.RESET}  {Style.BOLD}Current Bandwidth   :{Style.RESET} {Style.BRIGHT_YELLOW}{mbps:.2f} Mbps{Style.RESET}")
    print(f"{Style.BRIGHT_GREEN}│{Style.RESET}  {Style.BOLD}Active Stream Count :{Style.RESET} {Style.BRIGHT_WHITE}{active_count} active clients{Style.RESET}")
    print(f"{Style.BRIGHT_GREEN}│{Style.RESET}  {Style.BOLD}Total Transferred   :{Style.RESET} {Style.BRIGHT_CYAN}{format_bytes(total_bytes)}{Style.RESET}")
    throttle_str = f"{throttle} Mbps" if throttle else "Unthrottled (Max Line Speed)"
    print(f"{Style.BRIGHT_GREEN}│{Style.RESET}  {Style.BOLD}Bandwidth Limit     :{Style.RESET} {Style.DIM}{throttle_str}{Style.RESET}")
    print(f"{Style.BRIGHT_GREEN}└───" + "─" * 74 + f"┘{Style.RESET}\n")


def play_item(
    reader: Any,
    ep_id: int,
    player_target: Optional[str] = None,
    server_mgr: Optional[CLIStreamingServer] = None,
    port: int = 8787
) -> bool:
    """Starts local streaming server and launches selected player."""
    entry = None
    for e in reader.entries:
        if e.get("id") == ep_id:
            entry = e
            break

    if not entry:
        print(f"{Style.BRIGHT_RED}[!] Error: Invalid ID {ep_id}. Available: 1 to {len(reader.entries)}{Style.RESET}")
        return False

    if server_mgr:
        server_mgr.start(reader)
        active_port = server_mgr.port
    else:
        active_port = port

    comps = import_components()
    launch_stream_fn = comps["launch_stream"]

    encoded_name = urllib.parse.quote(entry.get("name", f"video_{ep_id}"))
    stream_url = f"http://127.0.0.1:{active_port}/stream/{ep_id}/{encoded_name}"
    
    name = entry.get("name", "")
    size = format_bytes(entry.get("size_bytes", 0))
    print(f"\n{Style.BRIGHT_GREEN}[✓] Streaming Episode {ep_id}:{Style.RESET} {Style.BOLD}{name}{Style.RESET} ({size})")
    print(f"    {Style.DIM}Stream URL:{Style.RESET} {Style.BRIGHT_CYAN}{Style.UNDERLINE}{stream_url}{Style.RESET}")

    result = launch_stream_fn(player_target, stream_url)
    if result.get("success"):
        pname = result.get("player", "Player")
        print(f"{Style.BRIGHT_GREEN}[✓] Launched in {pname} successfully!{Style.RESET}\n")
        return True
    else:
        err = result.get("error", "Unknown error")
        print(f"{Style.BRIGHT_RED}[!] Failed to launch player: {err}{Style.RESET}")
        print(f"{Style.BRIGHT_YELLOW}[*] You can copy the Stream URL above and open it manually in any player.{Style.RESET}\n")
        return False


def run_interactive_loop(reader: Any, server_mgr: CLIStreamingServer, port: int):
    """Interactive command loop for ZipStreamHub CLI."""
    inspect_cache: Dict[int, Dict[str, Any]] = {}

    print_archive_overview(reader)
    print_video_table(reader, inspect_cache)

    help_menu = f"""
{Style.BOLD}Interactive Commands:{Style.RESET}
  {Style.BRIGHT_GREEN}p <id>{Style.RESET}        : Play episode in default/detected player (e.g. {Style.CYAN}p 1{Style.RESET})
  {Style.BRIGHT_YELLOW}p <id> <name>{Style.RESET} : Play with specific player (e.g. {Style.CYAN}p 1 vlc{Style.RESET}, {Style.CYAN}p 1 mpv{Style.RESET}, {Style.CYAN}p 1 potplayer{Style.RESET})
  {Style.BRIGHT_CYAN}w <id>{Style.RESET}        : Open episode in Web Browser
  {Style.BRIGHT_MAGENTA}m3u [file]{Style.RESET}   : Export M3U playlist file (default: {Style.DIM}playlist.m3u{Style.RESET})
  {Style.BRIGHT_MAGENTA}strm [file]{Style.RESET}  : Export STRM ZIP bundle for Kodi/Jellyfin/Emby (default: {Style.DIM}strm_bundle.zip{Style.RESET})
  {Style.BRIGHT_WHITE}list{Style.RESET}          : Re-display file table
  {Style.BRIGHT_WHITE}stats{Style.RESET}         : View active streaming throughput & metrics
  {Style.BRIGHT_RED}q / exit{Style.RESET}      : Quit CLI
"""
    print(help_menu)

    while True:
        try:
            cmd = input(f"{Style.BRIGHT_CYAN}ZipStream > {Style.RESET}").strip()
        except (KeyboardInterrupt, EOFError):
            print(f"\n{Style.DIM}Exiting ZipStreamHub CLI.{Style.RESET}")
            break

        if not cmd:
            continue

        parts = cmd.split()
        action = parts[0].lower()

        if action in ("q", "quit", "exit"):
            print(f"{Style.DIM}Shutting down server and exiting...{Style.RESET}")
            server_mgr.stop()
            print(f"{Style.BRIGHT_GREEN}[✓] Goodbye!{Style.RESET}")
            break

        elif action == "list" or action == "ls":
            print_archive_overview(reader)
            print_video_table(reader, inspect_cache)

        elif action == "stats":
            print_active_stats()

        elif action == "m3u":
            out_file = parts[1] if len(parts) > 1 else "playlist.m3u"
            base_url = f"http://127.0.0.1:{server_mgr.port}"
            try:
                path = export_m3u_playlist(reader, out_file, base_url)
                print(f"{Style.BRIGHT_GREEN}[✓] M3U Playlist exported successfully:{Style.RESET} {Style.BOLD}{os.path.abspath(path)}{Style.RESET}")
            except Exception as e:
                print(f"{Style.BRIGHT_RED}[!] Error exporting M3U playlist: {e}{Style.RESET}")

        elif action == "strm":
            out_file = parts[1] if len(parts) > 1 else "strm_bundle.zip"
            base_url = f"http://127.0.0.1:{server_mgr.port}"
            try:
                path = export_strm_bundle(reader, out_file, base_url)
                print(f"{Style.BRIGHT_GREEN}[✓] STRM ZIP bundle exported successfully:{Style.RESET} {Style.BOLD}{os.path.abspath(path)}{Style.RESET}")
            except Exception as e:
                print(f"{Style.BRIGHT_RED}[!] Error exporting STRM bundle: {e}{Style.RESET}")

        elif action in ("p", "play"):
            if len(parts) < 2:
                print(f"{Style.BRIGHT_YELLOW}[!] Usage: p <id> [player_name] (e.g. p 1 or p 1 vlc){Style.RESET}")
                continue
            try:
                ep_id = int(parts[1])
                target_player = parts[2].lower() if len(parts) > 2 else None
                play_item(reader, ep_id, player_target=target_player, server_mgr=server_mgr, port=port)
            except ValueError:
                print(f"{Style.BRIGHT_RED}[!] Invalid episode ID: '{parts[1]}'. Must be a number.{Style.RESET}")

        elif action in ("w", "web", "browser"):
            if len(parts) < 2:
                print(f"{Style.BRIGHT_YELLOW}[!] Usage: w <id> (e.g. w 1){Style.RESET}")
                continue
            try:
                ep_id = int(parts[1])
                play_item(reader, ep_id, player_target="browser", server_mgr=server_mgr, port=port)
            except ValueError:
                print(f"{Style.BRIGHT_RED}[!] Invalid episode ID: '{parts[1]}'. Must be a number.{Style.RESET}")

        elif action.isdigit():
            # Quick numeric shortcut
            ep_id = int(action)
            play_item(reader, ep_id, player_target=None, server_mgr=server_mgr, port=port)

        elif action == "help" or action == "?":
            print(help_menu)

        else:
            print(f"{Style.BRIGHT_YELLOW}[!] Unknown command '{cmd}'. Type 'help' for available commands.{Style.RESET}")


def build_arg_parser() -> argparse.ArgumentParser:
    """Constructs command line argument parser."""
    parser = argparse.ArgumentParser(
        description="ZipStreamHub — High-Performance Remote ZIP Video Player & Stream Suite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Interactive Mode:
    python cli.py "https://example.com/archive.zip"
    
  Non-Interactive Streaming:
    python cli.py "https://example.com/archive.zip" --play 1 --player vlc
    python cli.py "https://example.com/archive.zip" --play 2 --player potplayer
    python cli.py "https://example.com/archive.zip" --play 1 --player browser

  Export Playlists:
    python cli.py "https://example.com/archive.zip" --export-m3u season1.m3u
    python cli.py "https://example.com/archive.zip" --export-strm library.zip

  List Contents:
    python cli.py "https://example.com/archive.zip" --list
"""
    )
    parser.add_argument("url", nargs="?", help="Remote ZIP archive HTTP/HTTPS URL")
    parser.add_argument("--play", "--ep", dest="play_id", type=int, default=None, help="Directly play specified episode ID")
    parser.add_argument("--player", dest="player", type=str, default=None, help="Target media player (potplayer, vlc, mpv, mpc-hc, mpc-be, iina, browser)")
    parser.add_argument("--export-m3u", dest="export_m3u", type=str, default=None, help="Export M3U playlist to specified filepath")
    parser.add_argument("--export-strm", dest="export_strm", type=str, default=None, help="Export STRM ZIP bundle to specified filepath")
    parser.add_argument("--list", "-l", dest="list_only", action="store_true", help="Print video list and archive stats, then exit")
    parser.add_argument("--port", "-p", dest="port", type=int, default=8787, help="Local HTTP streaming server port (default: 8787)")
    return parser


def main():
    """Main CLI entrypoint."""
    parser = build_arg_parser()
    args = parser.parse_args()

    print_banner()

    comps = import_components()
    RemoteZipReader = comps["RemoteZipReader"]

    zip_url = args.url
    if not zip_url:
        # Prompt user if not passed as CLI argument
        print(f"{Style.BRIGHT_CYAN}[?] Enter Remote ZIP URL or direct media link:{Style.RESET}")
        try:
            zip_url = input(f"{Style.BOLD}URL > {Style.RESET}").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            sys.exit(0)

    if not zip_url:
        zip_url = "https://motionpicturepro55.mhjoybots.workers.dev/0:findpath?id=1C_oTML7by_QacdPcO6nQ7_jxPDjxygPy"
        print(f"{Style.DIM}[i] No URL provided. Using demo URL: {zip_url}{Style.RESET}\n")

    print(f"{Style.BRIGHT_YELLOW}[*] Probing remote ZIP central directory headers...{Style.RESET}")
    start_time = time.time()

    try:
        reader = RemoteZipReader(zip_url)
        elapsed = time.time() - start_time
    except Exception as e:
        print(f"\n{Style.BRIGHT_RED}[!] Failed to parse remote ZIP archive: {e}{Style.RESET}")
        print(f"{Style.YELLOW}Please verify that the URL is accessible and supports HTTP Range requests.{Style.RESET}")
        sys.exit(1)

    print(f"{Style.BRIGHT_GREEN}[✓] Archive parsed in {elapsed:.2f}s! ({len(reader.entries)} entries){Style.RESET}")

    # Start background streaming server
    server_mgr = CLIStreamingServer(port=args.port)

    # 1. Non-Interactive: List only
    if args.list_only:
        inspect_cache: Dict[int, Dict[str, Any]] = {}
        print_archive_overview(reader)
        print_video_table(reader, inspect_cache, probe_limit=50)
        sys.exit(0)

    # 2. Non-Interactive: Exports
    exported_any = False
    if args.export_m3u:
        base_url = f"http://127.0.0.1:{args.port}"
        try:
            path = export_m3u_playlist(reader, args.export_m3u, base_url)
            print(f"{Style.BRIGHT_GREEN}[✓] M3U Playlist exported to:{Style.RESET} {Style.BOLD}{os.path.abspath(path)}{Style.RESET}")
            exported_any = True
        except Exception as e:
            print(f"{Style.BRIGHT_RED}[!] Failed to export M3U: {e}{Style.RESET}")
            sys.exit(1)

    if args.export_strm:
        base_url = f"http://127.0.0.1:{args.port}"
        try:
            path = export_strm_bundle(reader, args.export_strm, base_url)
            print(f"{Style.BRIGHT_GREEN}[✓] STRM bundle exported to:{Style.RESET} {Style.BOLD}{os.path.abspath(path)}{Style.RESET}")
            exported_any = True
        except Exception as e:
            print(f"{Style.BRIGHT_RED}[!] Failed to export STRM: {e}{Style.RESET}")
            sys.exit(1)

    if exported_any and args.play_id is None:
        sys.exit(0)

    # 4. Non-Interactive: Play specific episode
    if args.play_id is not None:
        server_mgr.start(reader)
        success = play_item(reader, args.play_id, player_target=args.player, server_mgr=server_mgr, port=args.port)
        if success:
            print(f"{Style.DIM}[*] Streaming server running on port {server_mgr.port}. Press Ctrl+C to stop.{Style.RESET}")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print(f"\n{Style.BRIGHT_YELLOW}[*] Shutting down streaming server...{Style.RESET}")
                server_mgr.stop()
                print(f"{Style.BRIGHT_GREEN}[✓] Stopped.{Style.RESET}")
        sys.exit(0 if success else 1)

    # 5. Interactive Mode
    server_mgr.start(reader)
    try:
        run_interactive_loop(reader, server_mgr, args.port)
    finally:
        server_mgr.stop()


if __name__ == "__main__":
    main()

