"""
Shim entrypoint for backward compatibility.
Delegates cleanly to src.zipstream.cli.
"""
from __future__ import annotations

import sys
import os

# Ensure src/ is in sys.path
_src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

import zipstream.cli as _cli_mod
sys.modules["cli"] = _cli_mod

from zipstream.cli import *
from zipstream import cli

if __name__ == "__main__":
    cli.main()
