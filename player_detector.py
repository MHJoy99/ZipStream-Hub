"""
Shim entrypoint for backward compatibility.
Delegates cleanly to src.zipstream.player_detector.
"""
from __future__ import annotations

import sys
import os

_src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

import zipstream.player_detector as _pd_mod
sys.modules["player_detector"] = _pd_mod

from zipstream.player_detector import *
from zipstream import player_detector
