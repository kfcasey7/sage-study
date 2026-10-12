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


@router.post("/sessions/{session_id}/study-guide")
async def start(session_id: str, body: StartIn | None = None) -> dict:
    return study_guide.start(session_id, force=bool(body and body.force))


@router.get("/sessions/{session_id}/study-guide")
def get(session_id: str) -> dict:
    S.get_session(session_id)
    guide = study_guide.get_guide(session_id)
    return guide or {"status": "none", "content": None}


@router.post("/sessions/{session_id}/study-guide/sections/{subtopic_id}/retry")
async def retry_section(session_id: str, subtopic_id: str) -> dict:
    return study_guide.retry_section(session_id, subtopic_id)


@router.post("/sessions/{session_id}/study-guide/repair-diagram")
async def repair(session_id: str, body: RepairIn) -> dict:
    return await study_guide.repair_diagram(session_id, body.subtopic_id, body.error)


def _require_guide(session_id: str) -> dict:
    guide = study_guide.get_guide(session_id)
    if not guide or not any(s["status"] == "ready" for s in guide["content"]["sections"]):
        raise AppError("conflict", "The study guide isn't ready yet.")
    return guide


@router.post("/sessions/{session_id}/study-guide/export/markdown")
async def export_markdown(session_id: str) -> dict:
    guide = _require_guide(session_id)
    filename, text = export.guide_markdown(session_id, guide)
    path = await asyncio.to_thread(desktop.choose_save_path, filename, "Markdown files (*.md)")
    if path is None:
        return {"cancelled": True}
    if path.suffix.lower() != ".md":
        path = path.with_suffix(".md")
    path.write_text(text, encoding="utf-8")
    desktop.remember_export(path)
    return {"path": str(path)}


@router.get("/sessions/{session_id}/study-guide/export/markdown")
def preview_markdown(session_id: str) -> dict:
    filename, text = export.guide_markdown(session_id, _require_guide(session_id))
    return {"filename": filename, "markdown": text}


@router.post("/sessions/{session_id}/study-guide/export/pdf")
async def export_pdf(session_id: str, body: PdfIn) -> dict:
    _require_guide(session_id)
    browser = export.find_browser()
    if browser is None:
        return {"fallback": "print", "message": "No Chrome or Edge was found, so use your system's print dialog to save as PDF."}
    session = S.get_session(session_id)
    path = await asyncio.to_thread(desktop.choose_save_path, export.default_pdf_name(session_id), "PDF files (*.pdf)")
    if path is None:
        return {"cancelled": True}
    if path.suffix.lower() != ".pdf":
        path = path.with_suffix(".pdf")
    html = export.build_print_html(body.body_html, body.head_html, f"Study Guide: {session['title']}")
    token = export.new_print_job(html)
    try:
        await asyncio.to_thread(export.render_pdf, f"{runtime.server_url()}/api/print/{token}", Path(path), browser)
    finally:
        export.print_jobs.pop(token, None)
    desktop.remember_export(path)
    return {"path": str(path)}


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
