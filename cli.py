#!/usr/bin/env python3
"""
ZipStreamHub CLI Interactive Stream Player
Interactive terminal player for remote ZIP archives with direct episode selection,
multi-player launching (PotPlayer, VLC, MPV), and ANSI colorful terminal UI.
"""

import os
import sys
import time
import shutil
import subprocess
import threading
from typing import List, Dict, Optional, Any

# Ensure ANSI escape sequences are supported on Windows
if sys.platform == "win32":
    os.system("")

# ANSI Color Codes
class Style:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
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


def print_banner():
    banner = f"""
{Style.BRIGHT_CYAN}{Style.BOLD}================================================================================{Style.RESET}
{Style.BRIGHT_YELLOW}{Style.BOLD}           ⚡  ZipStreamHub — High-Speed Remote ZIP Player  ⚡{Style.RESET}
{Style.BRIGHT_CYAN}      Instant HTTP Range Seeking | Zero-Disk Extraction | Multi-Player Stream{Style.RESET}
{Style.BRIGHT_CYAN}{Style.BOLD}================================================================================{Style.RESET}
"""
    print(banner)


def format_bytes(size: int) -> str:
    if size >= 1024 ** 3:
        return f"{size / (1024 ** 3):.2f} GB"
    elif size >= 1024 ** 2:
        return f"{size / (1024 ** 2):.1f} MB"
    elif size >= 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size} B"


def detect_players() -> Dict[str, str]:
    """Find installed media players in common paths or PATH."""
    players = {}
    
    # 1. PotPlayer
    potplayer_candidates = [
        r"C:\Program Files\DAUM\PotPlayer\PotPlayerMini64.exe",
        r"C:\Program Files (x86)\DAUM\PotPlayer\PotPlayerMini.exe",
        r"C:\Program Files\DAUM\PotPlayer\PotPlayer64.exe",
        shutil.which("PotPlayerMini64.exe") or "",
        shutil.which("potplayer") or ""
    ]
    for p in potplayer_candidates:
        if p and os.path.exists(p):
            players["PotPlayer"] = p
            break

    # 2. VLC
    vlc_candidates = [
        r"C:\Program Files\VideoLAN\VLC\vlc.exe",
        r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
        shutil.which("vlc") or ""
    ]
    for p in vlc_candidates:
        if p and os.path.exists(p):
            players["VLC"] = p
            break

    # 3. MPV
    mpv_candidates = [
        r"C:\mpv\mpv.exe",
        r"C:\Program Files\mpv\mpv.exe",
        shutil.which("mpv") or ""
    ]
    for p in mpv_candidates:
        if p and os.path.exists(p):
            players["MPV"] = p
            break

    return players


def launch_player(stream_url: str, selected_player: Optional[str] = None):
    """Launch player or print copyable URL."""
    available = detect_players()
    
    player_path = None
    player_name = None

    if selected_player and selected_player in available:
        player_name = selected_player
        player_path = available[selected_player]
    elif available:
        # Default priority: PotPlayer > MPV > VLC
        for pref in ["PotPlayer", "MPV", "VLC"]:
            if pref in available:
                player_name = pref
                player_path = available[pref]
                break

    if player_path:
        print(f"{Style.BRIGHT_GREEN}[✓] Launching {player_name}:{Style.RESET} {Style.DIM}{player_path}{Style.RESET}")
        try:
            if player_name == "MPV":
                subprocess.Popen([player_path, "--force-window=immediate", stream_url])
            else:
                subprocess.Popen([player_path, stream_url])
            print(f"{Style.BRIGHT_GREEN}[✓] Player launched successfully.{Style.RESET}")
        except Exception as e:
            print(f"{Style.BRIGHT_RED}[!] Failed to launch {player_name}: {e}{Style.RESET}")
    else:
        print(f"{Style.BRIGHT_YELLOW}[!] No supported media player found automatically (PotPlayer, VLC, MPV).{Style.RESET}")
        print(f"{Style.BRIGHT_WHITE}[*] Copy the Stream URL above and open it in your favorite media player!{Style.RESET}")


def import_streaming_components():
    """Dynamically loads and initializes core engine and server components."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from engine import RemoteZipReader, StreamPrefetcher, HTTP_POOL
        from server import start_stream_server, ZipStreamWebHandler, ThreadedZipStreamServer, PORT
        return RemoteZipReader, start_stream_server, ZipStreamWebHandler, ThreadedZipStreamServer, PORT
    except Exception as e:
        print(f"{Style.BRIGHT_RED}[!] Error loading streaming engine: {e}{Style.RESET}")
        raise


def run_interactive_cli():
    print_banner()

    RemoteZipReader, start_stream_server, ZipStreamHandler, ThreadedHTTPServer, PORT = import_streaming_components()

    # Determine ZIP URL
    if len(sys.argv) > 1:
        zip_url = sys.argv[1].strip()
    else:
        print(f"{Style.BRIGHT_CYAN}[?] Enter Remote ZIP URL or direct media link:{Style.RESET}")
        zip_url = input(f"{Style.BOLD}URL > {Style.RESET}").strip()

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
        print(f"{Style.YELLOW}Please verify that the URL supports HTTP Range requests.{Style.RESET}")
        return

    print(f"\n{Style.BRIGHT_GREEN}[✓] Archive Parsed in {elapsed:.2f}s!{Style.RESET}")
    print(f"    {Style.BOLD}Total Archive Size:{Style.RESET} {Style.BRIGHT_WHITE}{format_bytes(reader.total_size)}{Style.RESET}")
    print(f"    {Style.BOLD}Total Files Found :{Style.RESET} {Style.BRIGHT_WHITE}{len(reader.entries)}{Style.RESET}\n")

    # Display clean table of entries
    print(f"{Style.BRIGHT_CYAN}{'ID':<4} | {'Status':<7} | {'Size':<10} | {'Method':<7} | {'Filename'}{Style.RESET}")
    print(f"{Style.DIM}{'-'*4}-+-{'-'*7}-+-{'-'*10}-+-{'-'*7}-+-{'-'*45}{Style.RESET}")

    for e in reader.entries:
        is_video = any(e['name'].lower().endswith(ext) for ext in ['.mkv', '.mp4', '.avi', '.mov', '.webm', '.ts', '.m4v'])
        badge = f"{Style.BRIGHT_GREEN}VIDEO{Style.RESET}" if is_video else f"{Style.DIM}FILE {Style.RESET}"
        size_str = format_bytes(e.get('size_bytes', int(e.get('size_gb', 0) * (1024**3))))
        method = e.get('method_name', 'STORE')
        color = Style.BRIGHT_WHITE if is_video else Style.DIM
        print(f"{e['id']:<4} | {badge} | {size_str:<10} | {method:<7} | {color}{e['name']}{Style.RESET}")

    print(f"\n{Style.BRIGHT_CYAN}{'='*80}{Style.RESET}")
    
    # Prompt for episode/file selection
    while True:
        try:
            choice = input(f"\n{Style.BRIGHT_YELLOW}Enter episode number (1-{len(reader.entries)}) or 'q' to quit:{Style.RESET} ").strip()
            if choice.lower() in ('q', 'quit', 'exit'):
                print(f"{Style.DIM}Exiting ZipStreamHub CLI.{Style.RESET}")
                return
            ep_idx = int(choice)
            if 1 <= ep_idx <= len(reader.entries):
                break
            print(f"{Style.BRIGHT_RED}Invalid index. Please enter a number between 1 and {len(reader.entries)}.{Style.RESET}")
        except ValueError:
            print(f"{Style.BRIGHT_RED}Invalid input. Please enter a valid number.{Style.RESET}")

    selected_entry = reader.entries[ep_idx - 1]
    data_start = reader.get_data_offset(selected_entry)
    file_size = selected_entry.get("size_bytes", int(selected_entry.get("size_gb", 0) * (1024**3)))

    print(f"\n{Style.BRIGHT_GREEN}[+] Selected Entry:{Style.RESET} {Style.BOLD}{selected_entry['name']}{Style.RESET}")
    print(f"    {Style.DIM}Size: {format_bytes(file_size)} | ZIP Offset: {data_start} | Compression: {selected_entry.get('method_name', 'STORE')}{Style.RESET}")

    # Set server state
    import server as server_mod
    with server_mod.ARCHIVE_LOCK:
        server_mod.CURRENT_READER = reader
        server_mod.CACHED_ENTRIES = {e["id"]: e for e in reader.entries}
        server_mod.READERS_BY_URL[reader.url] = reader

    # Build local streaming URL
    encoded_name = selected_entry['name'].split('/')[-1]
    stream_url = f"http://127.0.0.1:{PORT}/stream/{ep_idx}/{encoded_name}"

    print(f"\n{Style.BRIGHT_CYAN}================================================================================{Style.RESET}")
    print(f"{Style.BRIGHT_YELLOW}{Style.BOLD}🚀 LIVE STREAMING SERVER READY{Style.RESET}")
    print(f"   {Style.BRIGHT_WHITE}Stream URL :{Style.RESET} {Style.BRIGHT_GREEN}{Style.UNDERLINE}{stream_url}{Style.RESET}")
    print(f"   {Style.BRIGHT_WHITE}Local Port :{Style.RESET} {Style.BRIGHT_WHITE}{PORT}{Style.RESET}")
    print(f"{Style.BRIGHT_CYAN}================================================================================{Style.RESET}\n")

    # Launch detected media player
    launch_player(stream_url)

    print(f"\n{Style.DIM}[*] Server active and listening on port {PORT}. Press Ctrl+C to stop streaming.{Style.RESET}\n")
    server = ThreadedHTTPServer(("127.0.0.1", PORT), ZipStreamHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print(f"\n{Style.BRIGHT_YELLOW}[*] Shutting down ZipStreamHub streaming server...{Style.RESET}")
        server.shutdown()
        print(f"{Style.BRIGHT_GREEN}[✓] Stopped cleanly.{Style.RESET}")


def main():
    """Main entrypoint for CLI command execution."""
    run_interactive_cli()


if __name__ == "__main__":
    main()
