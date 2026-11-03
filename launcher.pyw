"""Run Sage Study from a developer checkout, with no console window. Installed copies use `sage-study-gui`.

    .venv/Scripts/pythonw.exe launcher.pyw      (Windows)
    .venv/bin/python launcher.pyw               (macOS / Linux)
"""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "backend"))
os.chdir(ROOT)

from sage.cli import main  # noqa: E402

sys.exit(main())
