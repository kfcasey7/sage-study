"""Sage Study launcher. The desktop shortcut runs this with pythonw (no console window).

    .venv/Scripts/pythonw.exe launcher.pyw      (Windows)
    .venv/bin/python launcher.pyw               (macOS / Linux)
"""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "backend"))
os.chdir(ROOT)

from sage.main import main  # noqa: E402

sys.exit(main())
