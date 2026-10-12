"""Upload validation, text extraction (DOCX/PPTX/TXT/MD), image normalisation, and conversion
of stored uploads into Claude content blocks."""
from __future__ import annotations

import base64
import io
import shutil
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError

from . import config, db
from .errors import AppError


def _kind_for(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    kind = config.SUPPORTED_EXTENSIONS.get(ext)
    if not kind:
        supported = ", ".join(sorted({e.lstrip(".").upper() for e in config.SUPPORTED_EXTENSIONS}))
        raise AppError("unsupported_file", f"'{filename}' isn't a supported file type. Supported types: {supported}.")
    return kind


def _decode_text(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            text = data.decode(enc)
            if enc == "utf-16" and not data.startswith((b"\xff\xfe", b"\xfe\xff")):
                continue
            return text
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def extract_docx(data: bytes) -> str:
    from docx import Document

    doc = Document(io.BytesIO(data))
    lines: list[str] = []
    for block in doc.element.body.iterchildren():
        tag = block.tag.rsplit("}", 1)[-1]
        if tag == "p":
            from docx.text.paragraph import Paragraph

            p = Paragraph(block, doc)
            text = p.text.strip()
            if not text:
                continue
            style = (p.style.name if p.style is not None else "") or ""
            if style.lower().startswith("heading"):
                level = "".join(ch for ch in style if ch.isdigit()) or "1"
                lines.append("#" * min(int(level), 6) + " " + text)
            elif style.lower().startswith("list"):
                lines.append("- " + text)
            else:
                lines.append(text)
        elif tag == "tbl":
            from docx.table import Table

            table = Table(block, doc)
            for row in table.rows:
                cells = [c.text.strip().replace("\n", " ") for c in row.cells]
                lines.append("| " + " | ".join(cells) + " |")
            lines.append("")
    return "\n".join(lines).strip()


def _shape_text(shape) -> list[str]:
    out: list[str] = []
    if shape.shape_type == 6 and hasattr(shape, "shapes"):  # group
        for s in shape.shapes:
            out.extend(_shape_text(s))
    if getattr(shape, "has_text_frame", False) and shape.has_text_frame:
        for para in shape.text_frame.paragraphs:
            t = "".join(r.text for r in para.runs).strip()
            if t:
                out.append(("  " * para.level) + "- " + t if para.level else t)
    if getattr(shape, "has_table", False) and shape.has_table:
        for row in shape.table.rows:
            out.append("| " + " | ".join(c.text.strip().replace("\n", " ") for c in row.cells) + " |")
    return out


def extract_pptx(data: bytes) -> str:
    from pptx import Presentation

    prs = Presentation(io.BytesIO(data))
    parts: list[str] = []
    for i, slide in enumerate(prs.slides, 1):
        lines = []
        for shape in slide.shapes:
            lines.extend(_shape_text(shape))
        notes = ""
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None:
            notes = slide.notes_slide.notes_text_frame.text.strip()
        body = "\n".join(lines)
        if notes:
            body += f"\n\nSpeaker notes: {notes}"
        parts.append(f"## Slide {i}\n{body}".rstrip())
    return "\n\n".join(parts).strip()


def normalize_image(data: bytes, ext: str) -> tuple[bytes, str]:
    """Fix phone-photo rotation, downscale to Claude's useful resolution, re-encode."""
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError) as e:
        raise AppError("unsupported_file", "This image couldn't be read. It may be corrupted.") from e
    img = ImageOps.exif_transpose(img)
    if max(img.size) > config.IMAGE_MAX_EDGE:
        img.thumbnail((config.IMAGE_MAX_EDGE, config.IMAGE_MAX_EDGE), Image.LANCZOS)
    buf = io.BytesIO()
    if ext == ".png":
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue(), "image/png"
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    img.save(buf, format="JPEG", quality=88)
    return buf.getvalue(), "image/jpeg"


def save_upload(filename: str, data: bytes) -> dict[str, Any]:
    filename = Path(filename).name or "upload"
    kind = _kind_for(filename)
    ext = Path(filename).suffix.lower()
    if not data:
        raise AppError("unsupported_file", f"'{filename}' is empty.")
    if len(data) > config.MAX_FILE_MB * 1024 * 1024:
        raise AppError("file_too_large", f"'{filename}' is larger than {config.MAX_FILE_MB} MB. Split it or export only the pages you need.")

    upload_id = db.new_id()
    folder = config.UPLOAD_DIR / upload_id
    folder.mkdir(parents=True, exist_ok=True)
    char_count = None
    try:
        if kind == "pdf":
            if not data.lstrip()[:5].startswith(b"%PDF"):
                raise AppError("unsupported_file", f"'{filename}' doesn't look like a valid PDF.")
            path = folder / "document.pdf"
            path.write_bytes(data)
            stored_kind, media_type = "pdf", "application/pdf"
        elif kind == "image":
            img_bytes, media_type = normalize_image(data, ext)
            path = folder / ("image.png" if media_type == "image/png" else "image.jpg")
            path.write_bytes(img_bytes)
            stored_kind = "image"
        else:
            try:
                if kind == "docx":
                    text = extract_docx(data)
                elif kind == "pptx":
                    text = extract_pptx(data)
                else:
                    text = _decode_text(data)
            except AppError:
                raise
            except Exception as e:  # python-docx / python-pptx raise assorted errors on bad files
                raise AppError("unsupported_file", f"'{filename}' couldn't be opened. Is it a valid {ext.upper().lstrip('.')} file?") from e
            if not text.strip():
                raise AppError("unsupported_file", f"No text was found in '{filename}'. If it's scanned, upload it as a PDF or images instead.")
            path = folder / "extracted.txt"
            path.write_text(text, encoding="utf-8")
            stored_kind, media_type, char_count = "text", "text/plain", len(text)
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise

    row = {
        "id": upload_id,
        "filename": filename,
        "kind": stored_kind,
        "source_type": kind,
        "media_type": media_type,
        "size": len(data),
        "path": str(path),
        "char_count": char_count,
        "created_at": db.now(),
    }
    db.insert("uploads", row)
    return public_upload(row)


def public_upload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "filename": row["filename"],
        "kind": row["kind"],
        "source_type": row["source_type"],
        "size": row["size"],
        "char_count": row["char_count"],
        "status": "ready",
    }


def delete_upload(upload_id: str) -> None:
    linked = db.query_one("SELECT 1 FROM session_documents WHERE upload_id = ?", (upload_id,))
    if linked:
        return  # still used by a saved session (needed for retests); keep the file
    row = db.query_one("SELECT path FROM uploads WHERE id = ?", (upload_id,))
    if row:
        shutil.rmtree(Path(row["path"]).parent, ignore_errors=True)
        db.execute("DELETE FROM uploads WHERE id = ?", (upload_id,))


def content_blocks(uploads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert stored uploads into Messages API content blocks."""
    blocks: list[dict[str, Any]] = []
    total = 0
    for u in uploads:
        path = Path(u["path"])
        if not path.exists():
            raise AppError("missing_file", f"The stored copy of '{u['filename']}' is missing. Start a new session and upload it again.")
        if u["kind"] == "pdf":
            data = base64.standard_b64encode(path.read_bytes()).decode("ascii")
            total += len(data)
            blocks.append({
                "type": "document",
                "source": {"type": "base64", "media_type": "application/pdf", "data": data},
                "title": u["filename"],
            })
        elif u["kind"] == "image":
            data = base64.standard_b64encode(path.read_bytes()).decode("ascii")
            total += len(data)
            blocks.append({"type": "text", "text": f"Image: {u['filename']}"})
            blocks.append({"type": "image", "source": {"type": "base64", "media_type": u["media_type"], "data": data}})
        else:
            text = path.read_text(encoding="utf-8")
            total += len(text.encode("utf-8"))
            blocks.append({
                "type": "document",
                "source": {"type": "text", "media_type": "text/plain", "data": text},
                "title": u["filename"],
            })
    if total > config.MAX_INLINE_BYTES * 4 // 3:
        mb = total / (1024 * 1024)
        raise AppError(
            "file_too_large",
            f"Together the uploads are too large to send in one request ({mb:.0f} MB encoded; the limit is about 30 MB). "
            "Remove some files or upload only the chapters you need.",
        )
    return blocks
