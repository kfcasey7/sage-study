from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .. import desktop, runtime
from ..errors import AppError
from ..services import export, study_guide
from ..services import sessions as S

router = APIRouter(prefix="/api", tags=["study-guide"])


class StartIn(BaseModel):
    force: bool = False


class RepairIn(BaseModel):
    subtopic_id: str
    error: str


class PdfIn(BaseModel):
    body_html: str
    head_html: str


class PathIn(BaseModel):
    path: str


def _session_guide_id(session_id: str) -> str:
    gid = study_guide.session_guide_id(session_id)
    if not gid:
        raise AppError("not_found", "No study guide for this session yet.")
    return gid


def _require_ready(guide_id: str) -> dict:
    guide = study_guide.require(guide_id)
    if not any(s["status"] == "ready" for s in guide["content"]["sections"]):
        raise AppError("conflict", "The study guide isn't ready yet.")
    return guide


async def _export_markdown(guide_id: str) -> dict:
    guide = _require_ready(guide_id)
    filename, text = export.guide_markdown(study_guide.meta(guide), guide)
    path = await asyncio.to_thread(desktop.choose_save_path, filename, "Markdown files (*.md)")
    if path is None:
        return {"cancelled": True}
    if path.suffix.lower() != ".md":
        path = path.with_suffix(".md")
    path.write_text(text, encoding="utf-8")
    desktop.remember_export(path)
    return {"path": str(path)}


async def _export_pdf(guide_id: str, body: PdfIn) -> dict:
    guide = _require_ready(guide_id)
    info = study_guide.meta(guide)
    browser = export.find_browser()
    if browser is None:
        return {"fallback": "print", "message": "No Chrome or Edge was found, so use your system's print dialog to save as PDF."}
    path = await asyncio.to_thread(desktop.choose_save_path, export.default_pdf_name(info), "PDF files (*.pdf)")
    if path is None:
        return {"cancelled": True}
    if path.suffix.lower() != ".pdf":
        path = path.with_suffix(".pdf")
    html = export.build_print_html(body.body_html, body.head_html, f"Study Guide: {info['title']}")
    token = export.new_print_job(html)
    try:
        await asyncio.to_thread(export.render_pdf, f"{runtime.server_url()}/api/print/{token}", Path(path), browser)
    finally:
        export.print_jobs.pop(token, None)
    desktop.remember_export(path)
    return {"path": str(path)}


# --- Weak-areas guide of a finished quiz (by session) ---------------------------------------------

@router.post("/sessions/{session_id}/study-guide")
async def start(session_id: str, body: StartIn | None = None) -> dict:
    return study_guide.guide_view(study_guide.start(session_id, force=bool(body and body.force)))


@router.get("/sessions/{session_id}/study-guide")
def get(session_id: str) -> dict:
    S.get_session(session_id)
    guide = study_guide.get_session_guide(session_id)
    return study_guide.guide_view(guide) if guide else {"status": "none", "content": None}


@router.post("/sessions/{session_id}/study-guide/sections/{subtopic_id}/retry")
async def retry_section(session_id: str, subtopic_id: str) -> dict:
    return study_guide.guide_view(study_guide.retry_section(_session_guide_id(session_id), subtopic_id))


@router.post("/sessions/{session_id}/study-guide/repair-diagram")
async def repair(session_id: str, body: RepairIn) -> dict:
    return await study_guide.repair_diagram(_session_guide_id(session_id), body.subtopic_id, body.error)


@router.post("/sessions/{session_id}/study-guide/export/markdown")
async def export_markdown(session_id: str) -> dict:
    return await _export_markdown(_session_guide_id(session_id))


@router.get("/sessions/{session_id}/study-guide/export/markdown")
def preview_markdown(session_id: str) -> dict:
    guide = _require_ready(_session_guide_id(session_id))
    filename, text = export.guide_markdown(study_guide.meta(guide), guide)
    return {"filename": filename, "markdown": text}


@router.post("/sessions/{session_id}/study-guide/export/pdf")
async def export_pdf(session_id: str, body: PdfIn) -> dict:
    return await _export_pdf(_session_guide_id(session_id), body)


# --- Any guide, by id (Study Set subtopic guides use these) ----------------------------------------

@router.get("/guides/{guide_id}")
def get_by_id(guide_id: str) -> dict:
    return study_guide.guide_view(study_guide.require(guide_id))


@router.post("/guides/{guide_id}/sections/{subtopic_id}/retry")
async def retry_by_id(guide_id: str, subtopic_id: str) -> dict:
    return study_guide.guide_view(study_guide.retry_section(guide_id, subtopic_id))


@router.post("/guides/{guide_id}/repair-diagram")
async def repair_by_id(guide_id: str, body: RepairIn) -> dict:
    return await study_guide.repair_diagram(guide_id, body.subtopic_id, body.error)


@router.post("/guides/{guide_id}/export/markdown")
async def export_markdown_by_id(guide_id: str) -> dict:
    return await _export_markdown(guide_id)


@router.post("/guides/{guide_id}/export/pdf")
async def export_pdf_by_id(guide_id: str, body: PdfIn) -> dict:
    return await _export_pdf(guide_id, body)


@router.delete("/guides/{guide_id}")
def delete_guide(guide_id: str) -> dict:
    from .. import db

    study_guide.require(guide_id)
    db.execute("DELETE FROM guides WHERE id = ?", (guide_id,))
    return {"ok": True}


@router.get("/print/{token}", response_class=HTMLResponse)
def print_page(token: str) -> str:
    html = export.print_jobs.get(token)
    if html is None:
        raise AppError("not_found", "Print job expired.")
    return html


@router.post("/reveal")
def reveal(body: PathIn) -> dict:
    return {"ok": desktop.reveal(body.path)}


@router.post("/open-file")
def open_file(body: PathIn) -> dict:
    return {"ok": desktop.open_file(body.path)}
