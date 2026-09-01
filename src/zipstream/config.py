"""
ZipStreamHub Configuration Loader & Dataclasses
Loads configuration from JSON file with environment variable overrides and sensible defaults.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8787
    debug: bool = False


@dataclass
class StreamingConfig:
    prefetch_buffer_size_mb: int = 1024
    slice_size_kb: int = 128
    max_concurrent_streams: int = 8
    chunk_timeout_seconds: int = 30

    @property
    def prefetch_buffer_bytes(self) -> int:
        """Returns prefetch buffer size in bytes."""
        return self.prefetch_buffer_size_mb * 1024 * 1024

    @property
    def slice_size_bytes(self) -> int:
        """Returns slice size in bytes."""
        return self.slice_size_kb * 1024


@dataclass
class PlayerSpec:
    name: str
    command: str
    args: List[str] = field(default_factory=lambda: ["{url}"])


@dataclass
class PlayersConfig:
    default_player: str = "mpv"
    available_players: Dict[str, PlayerSpec] = field(
        default_factory=lambda: {
            "mpv": PlayerSpec(
                name="MPV Media Player",
                command="mpv",
                args=["--force-window=immediate", "{url}"],
            ),
            "vlc": PlayerSpec(
                name="VLC Media Player",
                command="vlc",
                args=["{url}"],
            ),
            "potplayer": PlayerSpec(
                name="PotPlayer",
                command="potplayer",
                args=["{url}"],
            ),
            "iina": PlayerSpec(
                name="IINA (macOS)",
                command="iina",
                args=["{url}"],
            ),
            "browser": PlayerSpec(
                name="Web Browser Player",
                command="web",
                args=["{url}"],
            ),
        }
    )


@dataclass
class UIConfig:
    theme: str = "dark"
    accent_color: str = "#3b82f6"
    compact_mode: bool = False
    show_thumbnails: bool = True
    page_size: int = 50
    autoplay: bool = False


@dataclass
class AppConfig:
    server: ServerConfig = field(default_factory=ServerConfig)
    streaming: StreamingConfig = field(default_factory=StreamingConfig)
    players: PlayersConfig = field(default_factory=PlayersConfig)
    ui: UIConfig = field(default_factory=UIConfig)

    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        return asdict(self)

    def save(self, config_path: Optional[Path | str] = None) -> None:
        """Save current configuration back to JSON file."""
        target_path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config.json"


def _parse_players(data: Dict[str, Any]) -> PlayersConfig:
    default_player = data.get("default_player", "mpv")
    raw_players = data.get("available_players", {})
    players_dict: Dict[str, PlayerSpec] = {}

    for key, spec in raw_players.items():
        if isinstance(spec, dict):
            players_dict[key] = PlayerSpec(
                name=spec.get("name", key),
                command=spec.get("command", key),
                args=spec.get("args", ["{url}"]),
            )
        elif isinstance(spec, PlayerSpec):
            players_dict[key] = spec

    return PlayersConfig(
        default_player=default_player,
        available_players=players_dict if players_dict else PlayersConfig().available_players,
    )


def load_config(config_path: Optional[Path | str] = None) -> AppConfig:
    """
    Load AppConfig from a JSON file with optional environment variable overrides.
    
    Environment variables:
        ZIPSTREAM_HOST -> server.host (e.g. 0.0.0.0 or 127.0.0.1)
        ZIPSTREAM_PORT -> server.port (default: 8787)
        ZIPSTREAM_DEBUG -> server.debug (default: false)
        ZIPSTREAM_PREFETCH_MB -> streaming.prefetch_buffer_size_mb (default: 1024 MB, supports up to 5120 MB)
        ZIPSTREAM_SLICE_KB -> streaming.slice_size_kb (default: 128 KB, supports 64-1024 KB)
        ZIPSTREAM_DEFAULT_PLAYER -> players.default_player (e.g. mpv, potplayer, vlc)
        ZIPSTREAM_THEME -> ui.theme (e.g. dark, light)
    """
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    data: Dict[str, Any] = {}

    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"[Warning] Failed to read config from {path}: {e}. Using defaults.")

    # Parse Server Config
    server_data = data.get("server", {})
    server = ServerConfig(
        host=os.getenv("ZIPSTREAM_HOST", server_data.get("host", "0.0.0.0")),
        port=int(os.getenv("ZIPSTREAM_PORT", server_data.get("port", 8787))),
        debug=str(os.getenv("ZIPSTREAM_DEBUG", server_data.get("debug", False))).lower() in ("true", "1", "yes"),
    )

    # Parse Streaming Config
    streaming_data = data.get("streaming", {})
    prefetch_mb_raw = os.getenv(
        "ZIPSTREAM_PREFETCH_MB", streaming_data.get("prefetch_buffer_size_mb", 1024)
    )
    slice_kb_raw = os.getenv(
        "ZIPSTREAM_SLICE_KB", streaming_data.get("slice_size_kb", 128)
    )
    try:
        prefetch_mb = int(prefetch_mb_raw)
    except (ValueError, TypeError):
        prefetch_mb = 1024
    try:
        slice_kb = int(slice_kb_raw)
    except (ValueError, TypeError):
        slice_kb = 128

    streaming = StreamingConfig(
        prefetch_buffer_size_mb=prefetch_mb,
        slice_size_kb=slice_kb,
        max_concurrent_streams=int(
            streaming_data.get("max_concurrent_streams", 8)
        ),
        chunk_timeout_seconds=int(
            streaming_data.get("chunk_timeout_seconds", 30)
        ),
    )

    # Parse Players Config
    players_data = data.get("players", {})
    players = _parse_players(players_data)
    if env_player := os.getenv("ZIPSTREAM_DEFAULT_PLAYER"):
        players.default_player = env_player

    # Parse UI Config
    ui_data = data.get("ui", {})
    ui = UIConfig(
        theme=os.getenv("ZIPSTREAM_THEME", ui_data.get("theme", "dark")),
        accent_color=ui_data.get("accent_color", "#3b82f6"),
        compact_mode=bool(ui_data.get("compact_mode", False)),
        show_thumbnails=bool(ui_data.get("show_thumbnails", True)),
        page_size=int(ui_data.get("page_size", 50)),
        autoplay=bool(ui_data.get("autoplay", False)),
    )

    return AppConfig(
        server=server,
        streaming=streaming,
        players=players,
        ui=ui,
    )


# Default global instance
config = load_config()


if __name__ == "__main__":
    cfg = load_config()
    print("Successfully loaded configuration:")
    print(f"  Server: {cfg.server.host}:{cfg.server.port} (debug={cfg.server.debug})")
    print(f"  Streaming: prefetch={cfg.streaming.prefetch_buffer_size_mb}MB ({cfg.streaming.prefetch_buffer_bytes:,} bytes), slice={cfg.streaming.slice_size_kb}KB ({cfg.streaming.slice_size_bytes:,} bytes)")
    print(f"  Default Player: {cfg.players.default_player}")
    print(f"  Available Players: {list(cfg.players.available_players.keys())}")
    print(f"  UI: theme={cfg.ui.theme}, accent={cfg.ui.accent_color}")
