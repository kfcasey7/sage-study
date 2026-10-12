"""Static configuration: paths, models, pricing, question types, difficulty labels."""
from __future__ import annotations

import os
from pathlib import Path

from platformdirs import user_data_dir

APP_NAME = "Sage Study"
APP_ID = "SageStudy"
VERSION = "1.0.0"

ROOT_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIST = ROOT_DIR / "frontend" / "dist"
ICON_DIR = ROOT_DIR / "assets" / "icon"

# SAGE_DATA_DIR lets tests (and power users) relocate all app data.
DATA_DIR = Path(os.environ.get("SAGE_DATA_DIR") or user_data_dir(APP_ID, appauthor=False))
DB_PATH = DATA_DIR / "sage.db"
UPLOAD_DIR = DATA_DIR / "uploads"
LOCK_FILE = DATA_DIR / "instance.lock"
LOG_FILE = DATA_DIR / "sage.log"

PREFERRED_PORT = 8765

KEYRING_SERVICE = APP_ID
KEYRING_USER = "anthropic_api_key"

# --- Models -----------------------------------------------------------------
DEFAULT_MODEL = "claude-sonnet-5-5"
MODELS = [
    {"id": "claude-sonnet-5-5", "label": "Claude Sonnet 5.5", "description": "Balanced speed and quality (recommended)"},
    {"id": "claude-opus-5-5", "label": "Claude Opus 5.5", "description": "Most thorough questions and grading, ~2x cost"},
    {"id": "claude-haiku-5-5", "label": "Claude Haiku 5.5", "description": "Fastest and cheapest"},
]
# Models that accept the server-side refusal fallback (`fallbacks: "default"`).
FALLBACK_MODELS = {"claude-sonnet-5-5", "claude-opus-5-5"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"

EFFORT_LEVELS = ["low", "medium", "high"]
DEFAULT_EFFORT = "medium"

# USD per million tokens. Cache writes are priced as multiples of input:
# 1.25x for the 5-minute TTL and 2x for the 1-hour TTL.
PRICING: dict[str, dict[str, float]] = {
    "claude-opus-5-5": {"input": 4.00, "output": 20.00, "cache_read": 0.20},
    "claude-sonnet-5-5": {"input": 2.00, "output": 10.00, "cache_read": 0.20},
    "claude-haiku-5-5": {"input": 0.10, "output": 0.50, "cache_read": 0.01},
}
CACHE_WRITE_5M_MULT = 1.25
CACHE_WRITE_1H_MULT = 2.0

# --- Study settings -----------------------------------------------------------
DIFFICULTY_LEVELS = {
    1: {"label": "Intro", "description": "Definitions, vocabulary, and basic recall"},
    2: {"label": "Review", "description": "Explain and connect ideas covered in class"},
    3: {"label": "Exam-level", "description": "Typical exam problems: apply concepts in familiar settings"},
    4: {"label": "Challenging", "description": "Multi-step problems, edge cases, and subtle distinctions"},
    5: {"label": "Expert", "description": "Synthesis across topics, novel situations, rigorous reasoning"},
}

# grading: "local" = deterministic, "claude" = rubric-graded by Claude,
# "hybrid" = local exact match first, Claude for anything that doesn't match.
QUESTION_TYPES = [
    {"id": "multiple_choice", "label": "Multiple choice", "grading": "local"},
    {"id": "select_all", "label": "Select all that apply", "grading": "local"},
    {"id": "true_false", "label": "True / False", "grading": "local"},
    {"id": "fill_blank", "label": "Fill in the blank", "grading": "hybrid"},
    {"id": "matching", "label": "Matching", "grading": "local"},
    {"id": "ordering", "label": "Ordering / sequencing", "grading": "local"},
    {"id": "short_response", "label": "Short response", "grading": "claude"},
    {"id": "long_response", "label": "Long response / essay", "grading": "claude"},
    {"id": "free_response", "label": "Free response", "grading": "claude"},
    {"id": "math", "label": "Mathematical response", "grading": "claude"},
    {"id": "code", "label": "Code", "grading": "claude"},
    {"id": "error_analysis", "label": "Error analysis", "grading": "claude"},
    {"id": "applied_scenario", "label": "Applied scenario", "grading": "claude"},
]
QUESTION_TYPE_IDS = [t["id"] for t in QUESTION_TYPES]
GRADING_MODE = {t["id"]: t["grading"] for t in QUESTION_TYPES}
TYPE_LABELS = {t["id"]: t["label"] for t in QUESTION_TYPES}

CODE_LANGUAGES = ["Python", "C++", "Java", "C", "MATLAB", "JavaScript"]

QUESTION_COUNTS = [5, 10, 15, 20]
MAX_QUESTIONS = 50
BATCH_SIZE = 5
POOL_AHEAD = 2  # non-adaptive: keep at least this many unanswered questions generated

WEAK_THRESHOLD = 70.0
CONFIDENTLY_WRONG_SCORE = 50.0

# --- Uploads ----------------------------------------------------------------
MAX_FILE_MB = 20
# The Messages API caps a request at 32 MB; base64 inflates binaries by ~4/3.
MAX_INLINE_BYTES = 22 * 1024 * 1024
IMAGE_MAX_EDGE = 1568
SUPPORTED_EXTENSIONS = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".pptx": "pptx",
    ".txt": "text",
    ".md": "text",
    ".markdown": "text",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
}

DEFAULT_SETTINGS = {
    "model": DEFAULT_MODEL,
    "effort": DEFAULT_EFFORT,
    "feedback_mode": "immediate",  # or "end"
    "theme": "light",
    "fallback_enabled": True,
}
