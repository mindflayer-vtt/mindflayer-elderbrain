"""Elderbrain host test package with an explicit production-module path."""

from pathlib import Path
import sys


LIBRARY = str(Path(__file__).resolve().parents[1] / "appliance/lib")
if LIBRARY not in sys.path:
    sys.path.insert(0, LIBRARY)
