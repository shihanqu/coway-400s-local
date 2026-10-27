#!/usr/bin/env python3
"""Configure a checkout using Python's standard library only."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from coway400s.cli import main

raise SystemExit(main(["init", *sys.argv[1:]]))
