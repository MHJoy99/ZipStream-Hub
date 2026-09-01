"""
Shim entrypoint for backward compatibility.
Delegates cleanly to src.zipstream.config.
"""
from __future__ import annotations

import sys
import os

# Ensure src/ is in sys.path
_src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

import zipstream.config as _cfg_mod
sys.modules["config"] = _cfg_mod

from zipstream.config import *
from zipstream import config
