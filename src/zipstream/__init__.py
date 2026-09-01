"""
ZipStreamHub - High-performance zero-disk streaming server and virtual archive extractor for remote ZIP / ZIP64 files.
"""

__version__ = "1.0.0"
__author__ = "ZipStreamHub Developers"
__license__ = "MIT"

from .engine import (
    RemoteZipReader,
    StreamPrefetcher,
    HTTP_POOL,
    MetricsTracker,
    METRICS,
    get_streaming_metrics,
    set_bandwidth_limit,
    calculate_adaptive_chunk_size,
)
from .server import ThreadedZipStreamServer, ZipStreamWebHandler
from .webdav_bridge import WebDAVBridge
from .config import AppConfig, ServerConfig, StreamingConfig, load_config
from .media_inspector import MediaInspector, inspect_media_header
from .history import HistoryManager, get_history_manager
from .cli import main

__all__ = [
    "__version__",
    "RemoteZipReader",
    "StreamPrefetcher",
    "ThreadedZipStreamServer",
    "MediaInspector",
    "HistoryManager",
    "MetricsTracker",
    "HTTP_POOL",
    "METRICS",
    "get_streaming_metrics",
    "set_bandwidth_limit",
    "calculate_adaptive_chunk_size",
    "ZipStreamWebHandler",
    "WebDAVBridge",
    "AppConfig",
    "ServerConfig",
    "StreamingConfig",
    "load_config",
    "inspect_media_header",
    "get_history_manager",
    "main",
]
