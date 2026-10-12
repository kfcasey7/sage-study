"""Upload validation and text extraction (PDF/DOCX/PPTX/TXT/MD), image normalisation, and assembly
of the material sent to the Claude Code CLI.

Text is sent inline in the prompt. Images and scanned PDFs (too little extractable text) are kept as
files; for those calls the CLI runs in a temp folder holding copies and reads them with its
read-only Read tool. Material longer than the per-call budget is split into chunks and the chunks
most relevant to the request are sent."""
from __future__ import annotations

import io
import math
import re
import shutil
from collections import Counter
from dataclasses import dataclass, field
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


def extract_pdf(data: bytes, filename: str) -> tuple[str, int]:
    """Text of every page, each prefixed with a [Page N] marker. Returns (text, page_count)."""
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception as e:  # noqa: BLE001
                raise AppError("unsupported_file", f"'{filename}' is password-protected. Remove the password and upload it again.") from e
        parts = []
        for i, page in enumerate(reader.pages, 1):
            try:
                page_text = page.extract_text() or ""
            except Exception:  # noqa: BLE001 - one bad page shouldn't sink the document
                page_text = ""
            page_text = re.sub(r"[ \t]+\n", "\n", page_text).strip()
            parts.append(f"[Page {i}]\n{page_text}")
        return "\n\n".join(parts), len(reader.pages)
    except AppError:
        raise
    except (PdfReadError, ValueError, KeyError, OSError) as e:
        raise AppError("unsupported_file", f"'{filename}' couldn't be read as a PDF. It may be corrupted.") from e


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
            original = folder / "document.pdf"
            original.write_bytes(data)
            text, pages = extract_pdf(data, filename)
            if pages and len(text) - len(f"[Page {pages}]") * pages >= config.SCANNED_PDF_CHARS_PER_PAGE * pages:
                path = folder / "extracted.txt"
                path.write_text(text, encoding="utf-8")
                stored_kind, media_type, char_count = "text", "text/plain", len(text)
            else:
                # Scanned (image-only) PDF: the CLI reads the file directly.
                path, stored_kind, media_type = original, "pdf", "application/pdf"
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


# --- Material assembly for CLI calls ---------------------------------------------------

@dataclass
class Material:
    """What a CLI call gets: inline text documents plus files the CLI reads from its working folder."""
    texts: list[tuple[str, str]] = field(default_factory=list)       # (title, text)
    files: list[tuple[str, Path, str]] = field(default_factory=list)  # (filename, stored path, description)

    @property
    def total_chars(self) -> int:
        return sum(len(t) for _, t in self.texts)


def load_material(uploads: list[dict[str, Any]]) -> Material:
    m = Material()
    for u in uploads:
        path = Path(u["path"])
        if not path.exists():
            raise AppError("missing_file", f"The stored copy of '{u['filename']}' is missing. Start a new session and upload it again.")
        if u["kind"] == "text":
            m.texts.append((u["filename"], path.read_text(encoding="utf-8")))
        elif u["kind"] == "image":
            m.files.append((u["filename"], path, "image (e.g. a photo of notes or slides)"))
        else:
            m.files.append((u["filename"], path, "scanned PDF; its text can't be extracted, so read its pages"))
    return m


_WORD = re.compile(r"[a-z][a-z0-9]{3,}")
_STOP = set("""about above after again against also among because been before being below between both could
does doing down during each from further have having here into itself just more most other over same should
some such than that their them then there these they this those through under until very were what when where
which while will with would your yours question questions answer student material subtopic slot type
difficulty""".split())


def _terms(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if w not in _STOP]


def split_chunks(text: str, size: int) -> list[str]:
    """Split on page markers / blank lines, packing paragraphs into chunks of about `size` chars."""
    paras = [p for p in re.split(r"\n\s*\n|(?=\[Page \d+\])", text) if p and p.strip()]
    chunks: list[str] = []
    cur = ""
    for p in paras:
        while len(p) > size:  # very long paragraph: hard-split
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(p[:size])
            p = p[size:]
        if cur and len(cur) + len(p) + 2 > size:
            chunks.append(cur)
            cur = ""
        cur = f"{cur}\n\n{p}" if cur else p
    if cur:
        chunks.append(cur)
    return chunks


def select_text(texts: list[tuple[str, str]], focus: str, budget: int, chunk_size: int) -> tuple[list[tuple[str, str]], bool]:
    """Fit documents into `budget` characters. Returns ([(title, text)], truncated).

    With a focus (e.g. the subtopics being tested), chunks are ranked by TF-IDF-style term overlap
    with it. Without one, chunks are sampled evenly so the whole material is represented. Selected
    chunks keep their original order, with an omission marker where text was skipped."""
    total = sum(len(t) for _, t in texts)
    if total <= budget:
        return texts, False

    chunks = [(di, ci, c) for di, (_, t) in enumerate(texts) for ci, c in enumerate(split_chunks(t, chunk_size))]
    n = len(chunks)
    focus_terms = Counter(_terms(focus))
    if focus_terms:
        df = Counter(w for _, _, c in chunks for w in set(_terms(c)))

        def score(c: str) -> float:
            tf = Counter(_terms(c))
            return sum(min(tf[w], 3) * math.log(1 + n / df[w]) * q for w, q in focus_terms.items() if tf[w])

        ranked = sorted(range(n), key=lambda i: (-score(chunks[i][2]), i))
    else:
        keep = max(1, budget // chunk_size)
        step = n / keep
        ranked = sorted({min(n - 1, int(i * step)) for i in range(keep)}) + list(range(n))

    chosen: set[int] = set()
    used = 0
    for i in ranked:
        if i in chosen:
            continue
        size = len(chunks[i][2]) + 20
        if used + size > budget:
            continue
        chosen.add(i)
        used += size

    out: list[tuple[str, str]] = []
    for di, (title, _) in enumerate(texts):
        idx = [i for i in sorted(chosen) if chunks[i][0] == di]
        if not idx:
            continue
        parts: list[str] = []
        prev = None
        for i in idx:
            gap = chunks[i][1] != 0 if prev is None else chunks[i][1] != chunks[prev][1] + 1
            if gap:
                parts.append("[... omitted ...]")
            parts.append(chunks[i][2])
            prev = i
        if chunks[idx[-1]][1] != max(c[1] for c in chunks if c[0] == di):
            parts.append("[... omitted ...]")
        out.append((title, "\n\n".join(parts)))
    return out, True
