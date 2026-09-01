"""
ZipStream Hub - Smart Media Player Detector & Stream Launcher
Supports auto-detection of popular Windows media players via standard installation paths
and Windows Registry (HKLM / HKCU App Paths & Software keys).
"""

import os
import sys
import shutil
import subprocess
import webbrowser
from typing import Dict, Optional, List

try:
    import winreg
except ImportError:
    winreg = None


PLAYER_DEFINITIONS = [
    {
        "key": "potplayer",
        "name": "Daum PotPlayer",
        "icon": "⚡",
        "executables": ["PotPlayerMini64.exe", "PotPlayerMini.exe", "PotPlayer64.exe", "PotPlayer.exe"],
        "paths": [
            r"C:\Program Files\DAUM\PotPlayer\PotPlayerMini64.exe",
            r"C:\Program Files (x86)\DAUM\PotPlayer\PotPlayerMini.exe",
            r"C:\Program Files\DAUM\PotPlayer\PotPlayer64.exe",
            r"C:\Program Files\DAUM\PotPlayer\PotPlayer.exe",
            r"D:\Program Files\DAUM\PotPlayer\PotPlayerMini64.exe",
            r"D:\DAUM\PotPlayer\PotPlayerMini64.exe",
        ],
        "reg_keys": [
            (r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\PotPlayerMini64.exe", None),
            (r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\PotPlayerMini.exe", None),
            (r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\PotPlayer64.exe", None),
            (r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\PotPlayer.exe", None),
            (r"SOFTWARE\DAUM\PotPlayer", "ProgramPath"),
            (r"SOFTWARE\DAUM\PotPlayer64", "ProgramPath"),
        ],
    },
    {
        "key": "vlc",
        "name": "VLC Media Player",
        "icon": "🎬",
        "executables": ["vlc.exe"],
        "paths": [
            r"C:\Program Files\VideoLAN\VLC\vlc.exe",
            r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
            r"D:\Program Files\VideoLAN\VLC\vlc.exe",
        ],
        "reg_keys": [
            (r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\vlc.exe", None),
            (r"SOFTWARE\VideoLAN\VLC", "InstallDir"),
        ],
    },
    {
        "key": "mpv",
        "name": "MPV Player",
        "icon": "▶️",
        "executables": ["mpv.exe"],
        "paths": [
            r"C:\Program Files\mpv\mpv.exe",
            r"C:\Program Files (x86)\mpv\mpv.exe",
            r"C:\mpv\mpv.exe",
            r"C:\tools\mpv\mpv.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\mpv\mpv.exe"),
            os.path.expandvars(r"%APPDATA%\mpv\mpv.exe"),
            os.path.expandvars(r"%USERPROFILE%\scoop\apps\mpv\current\mpv.exe"),
            os.path.expandvars(r"%ProgramData%\chocolatey\bin\mpv.exe"),
        ],
        "reg_keys": [
            (r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\mpv.exe", None),
        ],
    },
    {
        "key": "mpc-hc",
        "name": "MPC-HC",
        "icon": "📽️",
        "executables": ["mpc-hc64.exe", "mpc-hc.exe"],
        "paths": [
            r"C:\Program Files\MPC-HC\mpc-hc64.exe",
            r"C:\Program Files (x86)\MPC-HC\mpc-hc.exe",
            r"C:\Program Files\K-Lite Codec Pack\MPC-HC64\mpc-hc64.exe",
            r"C:\Program Files (x86)\K-Lite Codec Pack\MPC-HC\mpc-hc.exe",
            r"C:\Program Files (x86)\K-Lite Codec Pack\MPC-HC64\mpc-hc64.exe",
        ],
        "reg_keys": [
            (r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\mpc-hc64.exe", None),
            (r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\mpc-hc.exe", None),
            (r"SOFTWARE\MPC-HC\MPC-HC", "ExePath"),
        ],
    },
    {
        "key": "mpc-be",
        "name": "MPC-BE",
        "icon": "🎞️",
        "executables": ["mpc-be64.exe", "mpc-be.exe"],
        "paths": [
            r"C:\Program Files\MPC-BE x64\mpc-be64.exe",
            r"C:\Program Files\MPC-BE\mpc-be64.exe",
            r"C:\Program Files (x86)\MPC-BE\mpc-be.exe",
        ],
        "reg_keys": [
            (r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\mpc-be64.exe", None),
            (r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\mpc-be.exe", None),
            (r"SOFTWARE\MPC-BE", "ExePath"),
        ],
    },
    {
        "key": "iina",
        "name": "IINA",
        "icon": "🌌",
        "executables": ["iina.exe", "IINA.exe"],
        "paths": [
            r"C:\Program Files\IINA\IINA.exe",
            r"C:\Program Files (x86)\IINA\IINA.exe",
            "/Applications/IINA.app/Contents/MacOS/IINA",
        ],
        "reg_keys": [
            (r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\IINA.exe", None),
        ],
    },
]


def _clean_path(raw_path: str) -> Optional[str]:
    if not raw_path:
        return None
    cleaned = raw_path.strip().strip('"').strip("'")
    if os.path.isfile(cleaned) and os.path.exists(cleaned):
        return os.path.abspath(cleaned)
    if os.path.isdir(cleaned):
        # Look for typical executables inside folder
        for exe_candidate in ["PotPlayerMini64.exe", "PotPlayer64.exe", "vlc.exe", "mpv.exe", "mpc-hc64.exe", "mpc-be64.exe", "IINA.exe"]:
            candidate_path = os.path.join(cleaned, exe_candidate)
            if os.path.isfile(candidate_path):
                return os.path.abspath(candidate_path)
    return None


def _check_registry(reg_path: str, value_name: Optional[str] = None) -> Optional[str]:
    if not winreg:
        return None

    roots = [
        winreg.HKEY_LOCAL_MACHINE,
        winreg.HKEY_CURRENT_USER,
    ]

    # Check both 64-bit and 32-bit views of registry
    access_flags = [
        winreg.KEY_READ,
        winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0),
        winreg.KEY_READ | getattr(winreg, "KEY_WOW64_32KEY", 0),
    ]

    for root in roots:
        for flags in access_flags:
            try:
                with winreg.OpenKey(root, reg_path, 0, flags) as key:
                    val, _ = winreg.QueryValueEx(key, value_name if value_name else "")
                    found = _clean_path(str(val))
                    if found:
                        return found
            except OSError:
                continue
    return None


def get_installed_players() -> Dict[str, dict]:
    """
    Scans Windows Registry, known directory locations, and PATH environment
    for installed media players. Always includes 'browser' as a fallback.
    """
    detected: Dict[str, dict] = {}

    for player in PLAYER_DEFINITIONS:
        key = player["key"]
        found_exe: Optional[str] = None

        # 1. Search Registry App Paths & Software keys
        for reg_path, val_name in player.get("reg_keys", []):
            found_exe = _check_registry(reg_path, val_name)
            if found_exe:
                break

        # 2. Check predefined filesystem paths
        if not found_exe:
            for p in player.get("paths", []):
                cleaned = _clean_path(p)
                if cleaned:
                    found_exe = cleaned
                    break

        # 3. Check system PATH
        if not found_exe:
            for exe_name in player.get("executables", []):
                which_path = shutil.which(exe_name)
                if which_path:
                    found_exe = os.path.abspath(which_path)
                    break

        if found_exe:
            detected[key] = {
                "key": key,
                "name": player["name"],
                "icon": player.get("icon", "▶️"),
                "path": found_exe,
                "available": True,
            }

    # Always provide Web Browser playback fallback
    detected["browser"] = {
        "key": "browser",
        "name": "Default Web Browser",
        "icon": "🌐",
        "path": "system_browser",
        "available": True,
    }

    return detected


def launch_stream(player_key: Optional[str], stream_url: str) -> Dict[str, any]:
    """
    Launches the given stream URL in the requested player or highest priority detected player.
    """
    players = get_installed_players()
    target_key = player_key.lower().strip() if player_key else ""

    selected = None
    if target_key and target_key in players:
        selected = players[target_key]
    else:
        # Fallback priority: potplayer -> vlc -> mpv -> mpc-hc -> mpc-be -> iina -> browser
        priority = ["potplayer", "vlc", "mpv", "mpc-hc", "mpc-be", "iina", "browser"]
        for p in priority:
            if p in players:
                selected = players[p]
                break

    if not selected:
        return {"success": False, "error": "No media player or browser available."}

    if selected["key"] == "browser":
        webbrowser.open(stream_url)
        return {
            "success": True,
            "player": "Default Web Browser",
            "key": "browser",
            "message": "Opened stream in web browser.",
        }

    exe_path = selected["path"]
    try:
        # Launch detached process without blocking
        creationflags = 0
        if sys.platform == "win32":
            creationflags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

        subprocess.Popen(
            [exe_path, stream_url],
            creationflags=creationflags,
            close_fds=True if sys.platform != "win32" else False
        )
        return {
            "success": True,
            "player": selected["name"],
            "key": selected["key"],
            "path": exe_path,
            "message": f"Successfully launched {selected['name']}!",
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to launch {selected['name']}: {str(e)}",
            "fallback_url": stream_url,
        }


if __name__ == "__main__":
    if sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    print("Scanning installed media players...")
    installed = get_installed_players()
    for k, v in installed.items():
        print(f"[{v.get('icon', ' ')}] {v['name']} ({k}): {v['path']}")
