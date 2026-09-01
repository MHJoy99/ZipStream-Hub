"""
Shim entrypoint for backward compatibility.
Delegates cleanly to src.zipstream.media_inspector.
"""
from __future__ import annotations

import sys
import os

_src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

import zipstream.media_inspector as _mi_mod
sys.modules["media_inspector"] = _mi_mod

from zipstream.media_inspector import *
from zipstream import media_inspector
