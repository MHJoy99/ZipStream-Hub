"""
Shim entrypoint for backward compatibility.
Delegates cleanly to src.zipstream.subtitle_parser.
"""
from __future__ import annotations

import sys
import os

_src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

import zipstream.subtitle_parser as _sp
from zipstream.subtitle_parser import *
from zipstream import subtitle_parser

# Explicitly re-export internal helpers for backward compatibility & tests
_extract_episode_number = _sp._extract_episode_number
_detect_language = _sp._detect_language
