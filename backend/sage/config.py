"""Static configuration: paths, Claude Code CLI models, question types, difficulty labels."""
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

LLM_TMP_DIR = DATA_DIR / "llm_tmp"  # per-call folders of uploaded files the CLI may read

# --- Claude Code CLI ----------------------------------------------------------------
# All AI calls go through the locally installed `claude` CLI (Claude Code) in print mode, using
# the user's Claude subscription login. Model names are the CLI's aliases.
MODELS = [
    {"id": "haiku", "label": "Haiku", "description": "Fastest and lightest on your usage limits"},
    {"id": "sonnet", "label": "Sonnet", "description": "Careful grading and richer explanations"},
    {"id": "opus", "label": "Opus", "description": "Most capable; uses your limits fastest (plan permitting)"},
]
MODEL_IDS = [m["id"] for m in MODELS]
DEFAULT_MODEL_FAST = "haiku"    # topic mapping and question writing
DEFAULT_MODEL_SMART = "sonnet"  # grading written/math/code answers, study guides, diagram repair

# Which model tier each task uses.
TASK_TIER = {
    "topic_map": "fast",
    "generate": "fast",
    "grade": "smart",
    "study_guide": "smart",
    "diagram_repair": "smart",
    "chat": "smart",
}
# Seconds before a CLI call is killed.
TASK_TIMEOUT = {"topic_map": 240, "generate": 300, "grade": 180, "study_guide": 420, "diagram_repair": 120, "chat": 180}
MAX_CONCURRENT_CALLS = 2  # be gentle with subscription usage limits
VALIDATION_RETRIES = 2

# Inline document text budget per call (~4 chars/token). Longer material is chunked and the
# chunks most relevant to the request are sent.
DOC_CHAR_BUDGET = 120_000
CHUNK_CHARS = 4_000
# "Ask Claude" replies are about one question, so they get a smaller slice of the most relevant excerpts.
CHAT_DOC_CHAR_BUDGET = 30_000
CHAT_HISTORY_MESSAGES = 20   # earlier turns sent with each chat message
CHAT_MESSAGE_MAX_CHARS = 4_000
# A PDF averaging fewer extractable characters per page than this is treated as scanned, and the
# CLI reads the file itself.
SCANNED_PDF_CHARS_PER_PAGE = 200

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

CODE_LANGUAGES = ["Python", "C++", "Java", "C", "MATLAB", "JavaScript", "SQL", "JSON", "XML", "Assembly"]

QUESTION_COUNTS = [5, 10, 15, 20]
MAX_QUESTIONS = 50

# "Report question" reasons (id -> label shown to the student and passed to Claude when writing later questions).
REPORT_REASONS = [
    {"id": "wrong_answer", "label": "The answer key is wrong"},
    {"id": "unclear", "label": "Unclear or ambiguous"},
    {"id": "off_topic", "label": "Not about my material"},
    {"id": "broken", "label": "Broken formatting or missing information"},
    {"id": "other", "label": "Something else"},
]
REPORT_REASON_LABELS = {r["id"]: r["label"] for r in REPORT_REASONS}
REPORT_NOTE_MAX_CHARS = 1_000
FIRST_BATCH = 2  # small first batch so the student can start sooner
BATCH_SIZE = 3
POOL_AHEAD = 3  # non-adaptive: keep at least this many unanswered questions generated

WEAK_THRESHOLD = 70.0
CONFIDENTLY_WRONG_SCORE = 50.0

# --- Uploads ----------------------------------------------------------------
MAX_FILE_MB = 20
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
    "model_fast": DEFAULT_MODEL_FAST,
    "model_smart": DEFAULT_MODEL_SMART,
    "feedback_mode": "immediate",  # or "end"
    "theme": "light",
}
