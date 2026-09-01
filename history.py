"""
Shim entrypoint for backward compatibility.
Delegates cleanly to src.zipstream.history.
"""
from __future__ import annotations

import sys
import os

_src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

import zipstream.history as _hist_mod
sys.modules["history"] = _hist_mod

from zipstream.history import *
from zipstream import history
