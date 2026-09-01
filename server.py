"""
Shim entrypoint for backward compatibility.
Delegates cleanly to src.zipstream.server.
"""
from __future__ import annotations

import sys
import os

# Ensure src/ is in sys.path
_src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

# Import the actual module and re-export its attributes including module globals
import zipstream.server as _server_mod

# Alias sys.modules['server'] to zipstream.server so that tests mutating `server.CACHED_ENTRIES`
# directly mutate the exact same dictionary and globals as zipstream.server
sys.modules["server"] = _server_mod

from zipstream.server import *
from zipstream import server

if __name__ == "__main__":
    server.run_server()
