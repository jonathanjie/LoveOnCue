#!/usr/bin/env python3
"""Convenience launcher from an unpacked source archive; dependencies must be installed."""
from pathlib import Path
import sys
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'src'))
from wedding_ops.cli import main
sys.argv=[sys.argv[0],'demo',*sys.argv[1:]]
main()
