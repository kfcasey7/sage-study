"""The bundled sample Study Set behind "Try a demo". Its breakdown, guide, playlist, and quizzes were generated once
from samples/thermo-first-law.pdf (scripts/build_demo.py) and frozen, so loading it makes no AI calls and works before
Claude Code is set up. One quiz is finished; the other is ready to take, and its questions are all graded locally."""
from __future__ import annotations

import json
import shutil
from typing import Any

from .. import config, db

DEMO_FILE = config.DEMO_DIR / "demo_set.json"


def _rows_for(conn: Any, table: str, rows: list[dict[str, Any]]) -> None:
    columns = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    stamp = db.now()
    for row in rows:
        kept = {k: (stamp if k.endswith("_at") and v else v) for k, v in row.items() if k in columns}
        names = ", ".join(kept)
        marks = ", ".join("?" for _ in kept)
        conn.execute(f"INSERT INTO {table} ({names}) VALUES ({marks})", list(kept.values()))


def load() -> dict[str, str]:
    """Add the demo set, or return it if it's already there."""
    data = json.loads(DEMO_FILE.read_text(encoding="utf-8"))
    set_id = data["set_id"]
    if db.query_one("SELECT 1 FROM study_sets WHERE id = ?", (set_id,)):
        return {"id": set_id}
    for upload in data["tables"]["uploads"]:
        folder = config.data_path(upload["path"]).parent
        folder.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(config.DEMO_DIR / data["files"][upload["id"]], config.data_path(upload["path"]))
    with db.connect() as conn:
        for table, rows in data["tables"].items():
            _rows_for(conn, table, rows)
    return {"id": set_id}
