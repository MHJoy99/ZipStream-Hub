"""
Shim entrypoint for backward compatibility.
Delegates cleanly to src.zipstream.strm_generator.
"""
from __future__ import annotations

import sys
import os

_src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

import zipstream.strm_generator as _sg_mod
sys.modules["strm_generator"] = _sg_mod

from zipstream.strm_generator import *
from zipstream import strm_generator
