"""Study guide export: Markdown (built from the stored structure) and PDF (the rendered guide
printed by a headless Chromium browser, so KaTeX math and Mermaid SVGs come out as vector graphics)."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

from ..desktop import NO_WINDOW
from ..errors import AppError

# token -> html, served once at /api/print/{token} for the headless browser
print_jobs: dict[str, str] = {}


def safe_filename(text: str, fallback: str = "study-guide") -> str:
    name = re.sub(r"[^\w\- ]+", "", text).strip().replace(" ", "-")
    return (name[:60] or fallback).lower()


def guide_markdown(info: dict[str, Any], guide: dict[str, Any]) -> tuple[str, str]:
    """info: study_guide.meta(guide) (title, subject, date, kind)."""
    title = info["title"]
    content = guide["content"]
    lines = [f"# Study Guide: {title}", ""]
    meta = []
    if info["subject"]:
        meta.append(f"**Subject:** {info['subject']}")
    weak = info["kind"] == "weak_areas"
    meta.append(f"**{'Session' if weak else 'Created'}:** {info['date'][:10]}")
    if content.get("overall_score") is not None:
        meta.append(f"**{'Overall score' if weak else 'Quiz score on these subtopics'}:** {content['overall_score']:.0f}%")
    intro = ("This guide covers the subtopics where you scored below 70% or answered incorrectly with high confidence."
             if weak else "This guide covers the subtopics you chose from the Material Breakdown.")
    lines += ["  \n".join(meta), "", intro, ""]

    for sec in content["sections"]:
        s = sec.get("section")
        if sec["status"] != "ready" or not s:
            continue
        lines += [f"## {s['title']}", ""]
        if sec.get("score") is not None:
            lines += [f"_Your score on this subtopic: {sec['score']:.0f}%_", ""]
        lines += ["### Explanation", "", s["explanation"].strip(), ""]
        if s["key_formulas"]:
            lines += ["### Key formulas", ""]
            for f in s["key_formulas"]:
                lines += ["$$", f["latex"].strip(), "$$", "", f["description"].strip(), ""]
        d = s["diagram"]
        if d["include"] and d["mermaid"].strip():
            lines += ["### Diagram", "", "```mermaid", d["mermaid"].strip(), "```", ""]
            if d["caption"]:
                lines += [f"_{d['caption'].strip()}_", ""]
        c = s["chart"]
        if c["include"] and c["series"]:
            lines += [f"### Chart: {c['title']}", ""]
            for series in c["series"]:
                use_label = c["chart_type"] == "bar" and any(p["label"] for p in series["points"])
                x_head = c["x_label"] or "x"
                lines += [f"**{series['name']}**", "", f"| {x_head} | {c['y_label'] or 'y'} |", "|---|---|"]
                for p in series["points"]:
                    x = p["label"] if use_label else f"{p['x']:g}"
                    lines.append(f"| {x} | {p['y']:g} |")
                lines.append("")
            if c["caption"]:
                lines += [f"_{c['caption'].strip()}_", ""]
        w = s["worked_example"]
        lines += ["### Worked example", "", w["problem"].strip(), ""]
        lines += [f"{i}. {step.strip()}" for i, step in enumerate(w["steps"], 1)]
        lines += ["", f"**Answer:** {w['answer'].strip()}", ""]
        lines += ["### Common mistakes", ""]
        for m in s["common_mistakes"]:
            tag = " _(from your answers)_" if m["from_your_answers"] else ""
            lines += [f"- **{m['mistake'].strip()}**{tag}  ", f"  Why: {m['why'].strip()}  ", f"  Fix: {m['fix'].strip()}"]
        lines += ["", "### Practice questions", ""]
        for i, p in enumerate(s["practice_questions"], 1):
            lines += [f"**{i}.** {p['question'].strip()}", "", "<details><summary>Show answer</summary>", "", p["answer"].strip(), "", "</details>", ""]
    filename = f"{safe_filename(title)}-study-guide.md"
    return filename, "\n".join(lines).rstrip() + "\n"


def find_browser() -> str | None:
    candidates: list[str] = []
    if sys.platform == "win32":
        for base in (os.environ.get("PROGRAMFILES(X86)"), os.environ.get("PROGRAMFILES"), os.environ.get("LOCALAPPDATA")):
            if base:
                candidates += [
                    os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"),
                    os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"),
                ]
    elif sys.platform == "darwin":
        candidates += [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
    else:
        for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge"):
            found = shutil.which(name)
            if found:
                candidates.append(found)
    return next((c for c in candidates if c and os.path.exists(c)), None)


def build_print_html(body_html: str, head_html: str, title: str) -> str:
    return f"""<!doctype html>
<html lang="en" data-theme="light">
<head>
<meta charset="utf-8">
<title>{title}</title>
{head_html}
<style>
  @page {{ size: Letter; margin: 16mm 14mm; }}
  html, body {{ background: #fff !important; }}
  .no-print {{ display: none !important; }}
  details > *:not(summary) {{ display: block !important; }}
  .guide-section {{ break-inside: auto; }}
  svg, figure, .katex-display, pre {{ break-inside: avoid; }}
</style>
</head>
<body class="print-mode"><main class="print-root">{body_html}</main></body>
</html>"""


def render_pdf(url: str, out_path: Path, browser: str) -> None:
    profile = tempfile.mkdtemp(prefix="sage-print-")
    tmp_pdf = Path(profile) / "out.pdf"
    try:
        cmd = [
            browser, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
            "--disable-extensions", f"--user-data-dir={profile}", "--no-pdf-header-footer",
            "--virtual-time-budget=10000", f"--print-to-pdf={tmp_pdf}", url,
        ]
        proc = subprocess.run(cmd, capture_output=True, timeout=90, creationflags=NO_WINDOW)
        if not tmp_pdf.exists() or tmp_pdf.stat().st_size == 0:
            raise AppError("server_error", "PDF export failed.", detail=proc.stderr.decode(errors="replace")[-800:])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(tmp_pdf, out_path)
    except subprocess.TimeoutExpired as e:
        raise AppError("timeout", "PDF export took too long.") from e
    finally:
        shutil.rmtree(profile, ignore_errors=True)


def new_print_job(html: str) -> str:
    token = uuid.uuid4().hex
    print_jobs[token] = html
    return token


def default_pdf_name(info: dict[str, Any]) -> str:
    return f"{safe_filename(info['title'] or 'study')}-study-guide.pdf"

