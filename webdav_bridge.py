"""
Shim entrypoint for backward compatibility.
Delegates cleanly to src.zipstream.webdav_bridge.
"""
from __future__ import annotations

import sys
import os

_src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

import zipstream.webdav_bridge as _wd_mod
sys.modules["webdav_bridge"] = _wd_mod

from zipstream.webdav_bridge import *
from zipstream import webdav_bridge
