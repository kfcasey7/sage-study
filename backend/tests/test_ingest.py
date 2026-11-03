import io

import pytest
from PIL import Image

from sage import config, ingest
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
    text = config.data_path(ingest.db.query_one("SELECT path FROM uploads WHERE id = ?", (up["id"],))["path"]).read_text(encoding="utf-8")
    assert "# Laplace Transforms" in text and "| 1 | 1/s |" in text


def test_pptx_extraction_includes_slides_and_notes():
    up = ingest.save_upload("deck.pptx", pptx_bytes())
    text = config.data_path(ingest.db.query_one("SELECT path FROM uploads WHERE id = ?", (up["id"],))["path"]).read_text(encoding="utf-8")
    assert "## Slide 1" in text and "KCL" in text and "Speaker notes: Mention KVL" in text


def test_large_image_is_downscaled_and_rotated():
    img = Image.new("RGB", (4000, 3000), "white")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    up = ingest.save_upload("photo.JPG", buf.getvalue())
    row = ingest.db.query_one("SELECT * FROM uploads WHERE id = ?", (up["id"],))
    assert row["media_type"] == "image/jpeg"
    assert max(Image.open(config.data_path(row["path"])).size) == 1568


def text_pdf(pages: list[str]) -> bytes:
    from fpdf import FPDF

    pdf = FPDF()
    for text in pages:
        pdf.add_page()
        pdf.set_font("Helvetica", size=11)
        pdf.multi_cell(0, 6, text)
    return bytes(pdf.output())


def scanned_pdf() -> bytes:
    """An image-only PDF, like a phone scan: no extractable text."""
    from fpdf import FPDF

    img = io.BytesIO()
    Image.new("RGB", (400, 300), "white").save(img, format="PNG")
    img.seek(0)
    pdf = FPDF()
    pdf.add_page()
    pdf.image(img, x=10, y=10, w=180)
    return bytes(pdf.output())


def test_text_pdf_is_extracted_with_page_markers():
    page = "The first law of thermodynamics states that energy is conserved. " * 8
    up = ingest.save_upload("notes.pdf", text_pdf([page, "Second page about enthalpy. " * 10]))
    assert up["kind"] == "text" and up["source_type"] == "pdf" and up["char_count"] > 400
    m = ingest.load_material([ingest.db.query_one("SELECT * FROM uploads WHERE id = ?", (up["id"],))])
    title, text = m.texts[0]
    assert title == "notes.pdf" and "[Page 1]" in text and "[Page 2]" in text and "enthalpy" in text
    assert m.files == []


def test_scanned_pdf_is_kept_as_a_file_for_the_cli():
    up = ingest.save_upload("scan.pdf", scanned_pdf())
    assert up["kind"] == "pdf"
    m = ingest.load_material([ingest.db.query_one("SELECT * FROM uploads WHERE id = ?", (up["id"],))])
    assert m.texts == [] and m.files[0][0] == "scan.pdf" and m.files[0][1].suffix == ".pdf"
    assert "scanned" in m.files[0][2]


def test_material_mixes_text_and_files():
    txt = ingest.save_upload("b.md", "# Hi\nthere".encode())
    png = io.BytesIO()
    Image.new("RGBA", (10, 10)).save(png, format="PNG")
    img = ingest.save_upload("c.png", png.getvalue())
    rows = [ingest.db.query_one("SELECT * FROM uploads WHERE id = ?", (u["id"],)) for u in (txt, img)]
    m = ingest.load_material(rows)
    assert m.texts == [("b.md", "# Hi\nthere")]
    assert m.files[0][0] == "c.png" and m.files[0][1].suffix == ".png" and "image" in m.files[0][2]


def test_short_material_is_not_truncated():
    texts = [("a", "alpha " * 50), ("b", "beta " * 50)]
    assert ingest.select_text(texts, "anything", 10_000, 500) == (texts, False)


def test_long_material_keeps_chunks_relevant_to_focus():
    filler = "\n\n".join(f"Paragraph {i} about general housekeeping and logistics of the course." for i in range(400))
    key = "Entropy of an ideal gas increases during free expansion because the number of microstates grows."
    text = filler + "\n\n" + key + "\n\n" + filler
    out, truncated = ingest.select_text([("big.pdf", text)], "entropy microstates ideal gas", 3_000, 600)
    assert truncated
    joined = out[0][1]
    assert key in joined and len(joined) <= 3_200 and "[... omitted ...]" in joined


def test_long_material_without_focus_samples_evenly():
    text = "\n\n".join(f"[Page {i}]\nContent of page {i}. " + "x" * 300 for i in range(1, 101))
    out, truncated = ingest.select_text([("book.pdf", text)], "", 6_000, 700)
    assert truncated
    joined = out[0][1]
    present = [i for i in range(1, 101) if f"page {i}." in joined]
    assert present[0] == 1                       # the beginning,
    assert any(35 <= i <= 65 for i in present)   # the middle,
    assert present[-1] >= 80                     # and the end are all represented
    assert len(joined) <= 6_200


def test_split_chunks_respects_size():
    chunks = ingest.split_chunks("word " * 5000, 800)
    assert all(len(c) <= 800 for c in chunks) and len(chunks) > 20


@pytest.mark.parametrize("name,data,code", [
    ("virus.exe", b"MZ", "unsupported_file"),
    ("empty.txt", b"", "unsupported_file"),
    ("fake.pdf", b"hello", "unsupported_file"),
    ("broken.pdf", b"%PDF-1.4\n%garbage", "unsupported_file"),
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
    text = config.data_path(ingest.db.query_one("SELECT path FROM uploads WHERE id = ?", (up["id"],))["path"]).read_text(encoding="utf-8")
    assert text == "caf\xe9 – 50\xb0C"


def test_delete_keeps_files_linked_to_sessions():
    up = ingest.save_upload("keep.txt", b"hello")
    ingest.db.insert("session_documents", {"session_id": "s", "upload_id": up["id"], "position": 0})
    ingest.delete_upload(up["id"])
    assert ingest.db.query_one("SELECT 1 FROM uploads WHERE id = ?", (up["id"],))
