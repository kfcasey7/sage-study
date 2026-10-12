import base64
import io

import pytest
from PIL import Image

from sage import ingest
from sage.errors import AppError


def docx_bytes() -> bytes:
    from docx import Document

    d = Document()
    d.add_heading("Laplace Transforms", level=1)
    d.add_paragraph("The Laplace transform converts ODEs into algebra.")
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text = "f(t)", "F(s)"
    t.cell(1, 0).text, t.cell(1, 1).text = "1", "1/s"
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def pptx_bytes() -> bytes:
    from pptx import Presentation

    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "Kirchhoff's Laws"
    slide.placeholders[1].text = "KCL: currents into a node sum to zero"
    slide.notes_slide.notes_text_frame.text = "Mention KVL next."
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def test_docx_extraction_keeps_headings_and_tables():
    up = ingest.save_upload("notes.docx", docx_bytes())
    assert up["kind"] == "text" and up["source_type"] == "docx"
    text = open(ingest.db.query_one("SELECT path FROM uploads WHERE id = ?", (up["id"],))["path"], encoding="utf-8").read()
    assert "# Laplace Transforms" in text and "| 1 | 1/s |" in text


def test_pptx_extraction_includes_slides_and_notes():
    up = ingest.save_upload("deck.pptx", pptx_bytes())
    text = open(ingest.db.query_one("SELECT path FROM uploads WHERE id = ?", (up["id"],))["path"], encoding="utf-8").read()
    assert "## Slide 1" in text and "KCL" in text and "Speaker notes: Mention KVL" in text


def test_large_image_is_downscaled_and_rotated():
    img = Image.new("RGB", (4000, 3000), "white")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    up = ingest.save_upload("photo.JPG", buf.getvalue())
    row = ingest.db.query_one("SELECT * FROM uploads WHERE id = ?", (up["id"],))
    assert row["media_type"] == "image/jpeg"
    assert max(Image.open(row["path"]).size) == 1568


def test_content_blocks_shapes():
    pdf = ingest.save_upload("a.pdf", b"%PDF-1.4\n%fake\n")
    txt = ingest.save_upload("b.md", "# Hi\nthere".encode())
    png = io.BytesIO()
    Image.new("RGBA", (10, 10)).save(png, format="PNG")
    img = ingest.save_upload("c.png", png.getvalue())
    rows = [ingest.db.query_one("SELECT * FROM uploads WHERE id = ?", (u["id"],)) for u in (pdf, txt, img)]
    blocks = ingest.content_blocks(rows)
    assert blocks[0]["type"] == "document" and blocks[0]["source"]["media_type"] == "application/pdf"
    assert base64.b64decode(blocks[0]["source"]["data"]).startswith(b"%PDF")
    assert blocks[1]["source"] == {"type": "text", "media_type": "text/plain", "data": "# Hi\nthere"}
    assert blocks[2] == {"type": "text", "text": "Image: c.png"}
    assert blocks[3]["type"] == "image" and blocks[3]["source"]["media_type"] == "image/png"


@pytest.mark.parametrize("name,data,code", [
    ("virus.exe", b"MZ", "unsupported_file"),
    ("empty.txt", b"", "unsupported_file"),
    ("fake.pdf", b"hello", "unsupported_file"),
    ("broken.docx", b"not a zip", "unsupported_file"),
    ("broken.png", b"nope", "unsupported_file"),
    ("blank.txt", b"   \n  ", "unsupported_file"),
])
def test_rejects_bad_files(name, data, code):
    with pytest.raises(AppError) as e:
        ingest.save_upload(name, data)
    assert e.value.code == code


def test_too_large_file(monkeypatch):
    monkeypatch.setattr(ingest.config, "MAX_FILE_MB", 0)
    with pytest.raises(AppError) as e:
        ingest.save_upload("a.txt", b"x")
    assert e.value.code == "file_too_large"


def test_cp1252_text_decodes():
    up = ingest.save_upload("old.txt", "caf\xe9 – 50\xb0C".encode("cp1252"))
    text = open(ingest.db.query_one("SELECT path FROM uploads WHERE id = ?", (up["id"],))["path"], encoding="utf-8").read()
    assert text == "caf\xe9 – 50\xb0C"


def test_delete_keeps_files_linked_to_sessions():
    up = ingest.save_upload("keep.txt", b"hello")
    ingest.db.insert("session_documents", {"session_id": "s", "upload_id": up["id"], "position": 0})
    ingest.delete_upload(up["id"])
    assert ingest.db.query_one("SELECT 1 FROM uploads WHERE id = ?", (up["id"],))
