"""Study Set persistence helpers and the per-set Claude call context (like services/sessions.py for quizzes)."""
from __future__ import annotations

from collections import OrderedDict
from typing import Any

from .. import config, db, ingest
from ..errors import AppError
from ..llm_client import CallContext
from ..prompts.system import material_preamble
from . import sources as Src


def get_set(set_id: str) -> dict[str, Any]:
    row = db.query_one("SELECT * FROM study_sets WHERE id = ?", (set_id,))
    if not row:
        raise AppError("not_found", "That study set no longer exists.")
    row["breakdown"] = db.loads(row.pop("breakdown_json"), None)
    row["breakdown_error"] = db.loads(row.pop("breakdown_error_json"), None)
    return row


def update_set(set_id: str, **fields: Any) -> None:
    if "breakdown" in fields:
        fields["breakdown_json"] = db.dumps(fields.pop("breakdown"))
    if "breakdown_error" in fields:
        err = fields.pop("breakdown_error")
        fields["breakdown_error_json"] = db.dumps(err) if err is not None else None
    fields.setdefault("updated_at", db.now())
    db.update("study_sets", "id", set_id, fields)


def prompts(set_id: str) -> list[dict[str, Any]]:
    return db.query("SELECT id, text, version, created_at FROM set_prompts WHERE set_id = ? ORDER BY created_at, rowid", (set_id,))


def coverage_text(set_id: str) -> str:
    """Every prompt, oldest first: what the student wants covered."""
    return "\n\n".join(p["text"] for p in prompts(set_id))


def subtopic_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"], "name": row["name"], "summary": row["summary"],
        "key_concepts": db.loads(row["key_concepts_json"], []), "formulas": db.loads(row["formulas_json"], []),
        "difficulty": row["difficulty"], "source_ids": db.loads(row["source_ids_json"], []),
        "position": row["position"], "status": row["status"],
        "created_version": row["created_version"], "updated_version": row["updated_version"],
    }


def subtopics(set_id: str, include_removed: bool = False) -> list[dict[str, Any]]:
    rows = db.query("SELECT * FROM set_subtopics WHERE set_id = ? ORDER BY position", (set_id,))
    return [subtopic_row(r) for r in rows if include_removed or r["status"] == "active"]


def ready_uploads(set_id: str) -> list[tuple[str, dict[str, Any]]]:
    """(label, upload row) for every ready source, in position order."""
    labels = Src.labels(set_id)
    out = []
    for s in Src.set_sources(set_id):
        if s["status"] != "ready" or not s["upload_id"]:
            continue
        u = db.query_one("SELECT * FROM uploads WHERE id = ?", (s["upload_id"],))
        if u:
            out.append((labels[s["id"]], {**u, "filename": s["title"] or u["filename"]}))
    return out


def sources_key(set_id: str) -> str:
    return ",".join(sorted(s["id"] for s in Src.set_sources(set_id) if s["status"] == "ready"))


_material_cache: OrderedDict[tuple[str, str], ingest.Material] = OrderedDict()


def set_context(st: dict[str, Any], settings: dict[str, Any] | None = None) -> CallContext:
    """Material from the set's ready sources, each titled with its [S#] label so Claude can cite it."""
    key = (st["id"], sources_key(st["id"]))
    material = _material_cache.get(key)
    if material is None:
        material = ingest.Material()
        for label, u in ready_uploads(st["id"]):
            path = config.data_path(u["path"])
            if not path.exists():
                continue  # a missing stored copy just drops out of the material
            title = f"[{label}] {u['filename']}"
            if u["kind"] == "text":
                material.texts.append((title, path.read_text(encoding="utf-8")))
            elif u["kind"] == "image":
                material.files.append((title, path, "image (e.g. a photo of notes or slides)"))
            else:
                material.files.append((title, path, "scanned PDF; its text can't be extracted, so read its pages"))
        _material_cache[key] = material
        while len(_material_cache) > 4:
            _material_cache.popitem(last=False)
    settings = settings or db.get_settings()
    has_docs = bool(material.texts or material.files)
    return CallContext(
        session_id=None,
        model_fast=settings.get("model_fast", config.DEFAULT_MODEL_FAST),
        model_smart=settings.get("model_smart", config.DEFAULT_MODEL_SMART),
        material=material,
        preamble=material_preamble(coverage_text(st["id"]), st["subject"], has_docs),
    )
