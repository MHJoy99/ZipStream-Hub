"""
Shim entrypoint for backward compatibility.
Delegates cleanly to src.zipstream.control_panel.
"""
from __future__ import annotations

import sys
import os

# Ensure src/ is in sys.path
_src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

import zipstream.control_panel as _cp_mod
sys.modules["control_panel"] = _cp_mod

from zipstream.control_panel import *
from zipstream import control_panel

if __name__ == "__main__":
    control_panel.main()
