from __future__ import annotations

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel, Field

from .. import config, db
from ..errors import AppError
from ..services import breakdown, study_sets
from ..services import sources as Src
from .sessions import session_view

router = APIRouter(prefix="/api", tags=["study-sets"])


# --- Sources (setup screen drafts, or a set's Append panel) -----------------------------------------

@router.post("/sources/files")
async def add_file(file: UploadFile = File(...), set_id: str | None = Form(None), draft_id: str | None = Form(None)) -> dict:
    data = await file.read(config.MAX_FILE_MB * 1024 * 1024 + 1)
    return Src.add_file(file.filename or "upload", data, set_id=set_id, draft_id=draft_id)


class LinksIn(BaseModel):
    urls: list[str]
    set_id: str | None = None
    draft_id: str | None = None


@router.post("/sources/links")
async def add_links(body: LinksIn) -> list[dict]:
    if body.set_id:
        study_sets.C.get_set(body.set_id)
    return Src.add_links(body.urls, set_id=body.set_id, draft_id=body.draft_id)


@router.get("/sources")
def get_sources(ids: str = "") -> list[dict]:
    return Src.get_many([i for i in ids.split(",") if i])


@router.post("/sources/{source_id}/retry")
async def retry_source(source_id: str) -> dict:
    return Src.retry(source_id)


@router.delete("/sources/{source_id}")
def delete_source(source_id: str) -> dict:
    Src.remove(source_id)
    return {"ok": True}


# --- Sets --------------------------------------------------------------------------------------------

class SetIn(BaseModel):
    title: str = ""
    subject: str = ""
    prompt: str = ""
    source_ids: list[str] = Field(default_factory=list)


@router.post("/sets")
async def create_set(body: SetIn) -> dict:
    set_id = study_sets.create(subject=body.subject, title=body.title, prompt=body.prompt, source_ids=body.source_ids)
    return study_sets.view(set_id)


@router.get("/sets")
def list_sets() -> list[dict]:
    return study_sets.list_sets()


@router.get("/sets/{set_id}")
def get_set(set_id: str) -> dict:
    return study_sets.view(set_id)


class SetPatch(BaseModel):
    title: str | None = None
    subject: str | None = None


@router.patch("/sets/{set_id}")
def patch_set(set_id: str, body: SetPatch) -> dict:
    return study_sets.rename(set_id, body.title, body.subject)


@router.delete("/sets/{set_id}")
def delete_set(set_id: str) -> dict:
    study_sets.delete(set_id)
    return {"ok": True}


@router.post("/sets/{set_id}/breakdown")
async def build_breakdown(set_id: str) -> dict:
    """Build (migrated sets, failed builds) or rebuild the breakdown from the current prompts and sources."""
    return study_sets.rebuild(set_id)


class AppendIn(BaseModel):
    prompt: str = ""


@router.post("/sets/{set_id}/append")
async def append(set_id: str, body: AppendIn) -> dict:
    """Add a prompt and/or merge in sources added since the last breakdown."""
    return study_sets.append(set_id, body.prompt)


class MapRepairIn(BaseModel):
    error: str


@router.post("/sets/{set_id}/breakdown/repair-map")
async def repair_map(set_id: str, body: MapRepairIn) -> dict:
    return await breakdown.repair_map(set_id, body.error)


class QuizIn(BaseModel):
    subtopic_ids: list[str]
    types: list[str]
    difficulty: int = 3
    adaptive: bool = False
    count: int = 10
    languages: list[str] = Field(default_factory=list)


@router.post("/sets/{set_id}/quiz")
async def start_quiz(set_id: str, body: QuizIn) -> dict:
    sid = study_sets.start_quiz(set_id, subtopic_ids=body.subtopic_ids, types=body.types, difficulty=body.difficulty,
                                adaptive=body.adaptive, count=body.count, languages=body.languages or ["Python"],
                                settings=db.get_settings())
    return session_view(sid)


class SubtopicsIn(BaseModel):
    subtopic_ids: list[str]


@router.post("/sets/{set_id}/guides")
async def start_guide(set_id: str, body: SubtopicsIn) -> dict:
    return study_sets.start_guide(set_id, body.subtopic_ids)


@router.post("/sets/{set_id}/playlists")
async def start_playlist(set_id: str, body: SubtopicsIn) -> dict:
    from ..services import youtube

    study_sets.C.get_set(set_id)
    if not study_sets.C.subtopics(set_id):
        raise AppError("conflict", "This study set has no subtopics yet. Build the breakdown first.")
    return youtube.start_playlist(set_id, body.subtopic_ids)
