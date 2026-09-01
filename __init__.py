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
from .cli import main

__all__ = [
    "__version__",
    "RemoteZipReader",
    "StreamPrefetcher",
    "HTTP_POOL",
    "MetricsTracker",
    "METRICS",
    "get_streaming_metrics",
    "set_bandwidth_limit",
    "calculate_adaptive_chunk_size",
    "ThreadedZipStreamServer",
    "ZipStreamWebHandler",
    "WebDAVBridge",
    "AppConfig",
    "ServerConfig",
    "StreamingConfig",
    "load_config",
    "main",
]
