"""Reading links: web pages, PDFs, YouTube, Google files, and the ways a link can fail (all HTTP mocked)."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from sage.services import linkfetch as L

from .test_ingest import text_pdf


def tiny_pdf(text: str) -> bytes:
    return text_pdf([(text + ". ") * 40])
from .web_mock import ARTICLE


def fetch(url: str, **kw):
    return asyncio.run(L.fetch_link(url, **kw))


def test_web_page_main_text_and_title(web):
    web.html("https://example.com/thermo", ARTICLE)
    f = fetch("https://example.com/thermo")
    assert f.source_type == "web"
    assert f.title == "The First Law of Thermodynamics"
    assert "internal energy" in f.text and "isothermal" in f.text
    assert "Copyright" not in f.text and "Home | About" not in f.text  # boilerplate dropped


def test_url_without_scheme_and_honest_user_agent(web):
    web.html("https://example.com/thermo", ARTICLE)
    fetch("example.com/thermo")
    assert web.requests[-1].headers["user-agent"].startswith("SageStudy/")


def test_tiny_page_is_unreadable(web):
    web.html("https://example.com/app", "<html><head><title>App</title></head><body><div id=root></div></body></html>")
    with pytest.raises(L.LinkError, match="readable text"):
        fetch("https://example.com/app")


@pytest.mark.parametrize("status,phrase", [(401, "log in"), (402, "paywall"), (404, "wasn't found"), (429, "limiting")])
def test_http_errors(web, status, phrase):
    web.html("https://example.com/x", "no", status=status)
    with pytest.raises(L.LinkError, match=phrase):
        fetch("https://example.com/x")


def test_403_retries_as_browser_then_reports_blocked(web):
    web.html("https://example.com/blocked", "denied", status=403)
    with pytest.raises(L.LinkError, match="blocked"):
        fetch("https://example.com/blocked")
    agents = [r.headers["user-agent"] for r in web.requests if "blocked" in str(r.url)]
    assert len(agents) == 2 and agents[1].startswith("Mozilla/")


def test_403_then_browser_agent_succeeds(web):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.headers["user-agent"].startswith("Mozilla/"):
            return httpx.Response(200, text=ARTICLE, headers={"content-type": "text/html"})
        return httpx.Response(403, text="no bots")
    web.add("https://example.com/picky", handler)
    assert fetch("https://example.com/picky").title == "The First Law of Thermodynamics"


def test_login_redirect_is_unreadable(web):
    web.add("https://example.com/private", httpx.Response(302, headers={"location": "https://example.com/login?next=/private"}))
    web.html("https://example.com/login", ARTICLE)
    with pytest.raises(L.LinkError, match="login"):
        fetch("https://example.com/private")


def test_direct_pdf_link(web):
    pdf = tiny_pdf("Carnot efficiency")
    web.add("https://example.com/notes.pdf", httpx.Response(200, content=pdf, headers={"content-type": "application/pdf"}))
    f = fetch("https://example.com/notes.pdf")
    assert f.source_type == "web_pdf" and f.filename == "notes.pdf" and f.title == "notes" and f.file_bytes == pdf


def test_pdf_detected_by_magic_bytes(web):
    pdf = tiny_pdf("x")
    web.add("https://example.com/download?id=7", httpx.Response(
        200, content=pdf, headers={"content-type": "application/octet-stream", "content-disposition": 'attachment; filename="Lecture 3.pdf"'}))
    f = fetch("https://example.com/download?id=7")
    assert f.source_type == "web_pdf" and f.filename == "Lecture 3.pdf"


def test_too_large_download(web, monkeypatch):
    from sage import config
    monkeypatch.setattr(config, "MAX_FILE_MB", 0)
    web.add("https://example.com/big.pdf", httpx.Response(200, content=b"%PDF-" + b"0" * 5000, headers={"content-type": "application/pdf"}))
    with pytest.raises(L.LinkError, match="larger than"):
        fetch("https://example.com/big.pdf")


def test_youtube_transcript_and_title(web):
    f = fetch("https://youtu.be/NyOYW07-L5g?t=42", transcript=lambda vid: f"[0:00] hello from {vid}")
    assert f.source_type == "youtube"
    assert f.title == "Title NyOYW07-L5g"
    assert "hello from NyOYW07-L5g" in f.text and "watch?v=NyOYW07-L5g" in f.text


def test_youtube_without_transcript(web):
    def no_transcript(vid):
        raise L.LinkError("This video has no transcript available (captions are turned off)")
    with pytest.raises(L.LinkError, match="no transcript"):
        fetch("https://www.youtube.com/watch?v=NyOYW07-L5g", transcript=no_transcript)


def test_youtube_private_video(web):
    web.add("https://www.youtube.com/oembed", httpx.Response(401, text="Unauthorized"))
    with pytest.raises(L.LinkError, match="private"):
        fetch("https://www.youtube.com/watch?v=NyOYW07-L5g")


def test_real_transcript_errors_are_explained(monkeypatch):
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api._errors import TranscriptsDisabled

    def disabled(self, vid):
        raise TranscriptsDisabled(vid)
    monkeypatch.setattr(YouTubeTranscriptApi, "list", disabled)
    with pytest.raises(L.LinkError, match="no transcript"):
        L.fetch_transcript("NyOYW07-L5g")


def test_public_google_doc_uses_export_url(web):
    web.add("https://docs.google.com/document/d/abc123/export?format=txt", httpx.Response(
        200, text="﻿Enthalpy notes\nH = U + PV", headers={"content-type": "text/plain",
                                                               "content-disposition": "attachment; filename*=UTF-8''Enthalpy%20notes.txt"}))
    f = fetch("https://docs.google.com/document/d/abc123/edit?usp=sharing")
    assert f.source_type == "gdoc" and f.title == "Enthalpy notes" and "H = U + PV" in f.text


def test_private_google_doc(web):
    web.add("https://docs.google.com/document/d/secret/export", httpx.Response(
        302, headers={"location": "https://accounts.google.com/ServiceLogin?continue=x"}))
    web.html("https://accounts.google.com/", "<html>Sign in</html>")
    with pytest.raises(L.LinkError, match="isn't shared publicly"):
        fetch("https://docs.google.com/document/d/secret/edit")


def test_google_slides_export_as_pptx(web):
    web.add("https://docs.google.com/presentation/d/s1/export/pptx", httpx.Response(
        200, content=b"PK fake", headers={"content-type": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                                           "content-disposition": 'attachment; filename="Week 2.pptx"'}))
    f = fetch("https://docs.google.com/presentation/d/s1/edit#slide=id.p")
    assert f.source_type == "gslides" and f.filename == "Week 2.pptx" and f.file_bytes == b"PK fake"


def test_local_network_links_refused(web):
    for url in ("http://127.0.0.1:8765/api/settings", "http://localhost/x", "http://10.0.0.5/admin"):
        with pytest.raises(L.LinkError, match="local network"):
            fetch(url)


def test_redirect_to_local_network_refused(web):
    web.add("https://example.com/sneaky", httpx.Response(302, headers={"location": "http://127.0.0.1:8765/api/settings"}))
    with pytest.raises(L.LinkError, match="local network"):
        fetch("https://example.com/sneaky")


@pytest.mark.parametrize("raw", ["", "mailto:me@example.com", "ftp://example.com/file", "javascript:alert(1)", "not a link"])
def test_bad_links(raw):
    with pytest.raises(L.LinkError):
        L.clean_url(raw)


def test_math_is_kept_as_latex():
    html = """<html><head><title>Energy</title></head><body><article><p>The first law is
<span class="mwe-math-element"><span style="display:none"><math alttext="{\displaystyle \Delta U=Q-W}"><mi>U</mi></math></span>
<img alt="{\displaystyle \Delta U=Q-W}" src="x.svg"></span> for a closed system.<sup>[3]</sup></p>
<p>KaTeX: <span class="katex"><span class="katex-mathml"><math><semantics><annotation encoding="application/x-tex">H = U + PV</annotation></semantics></math></span><span class="katex-html">H=U+PV</span></span>.</p>
<p>MathJax: <script type="math/tex">\eta = 1 - T_c/T_h</script>.</p>
""" + "<p>" + "Padding text about thermodynamics. " * 20 + "</p></article></body></html>"
    title, text = L.extract_html(html, "https://example.com/e")
    assert "$\Delta U=Q-W$" in text and "$H = U + PV$" in text and "$\eta = 1 - T_c/T_h$" in text
    assert "[3]" not in text and text.count("Delta U") == 1
