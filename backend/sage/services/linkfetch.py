"""Reading links into study material, in the Python backend (the Claude Code CLI never fetches pages).

  * YouTube videos: the transcript (youtube-transcript-api) plus the title from oEmbed.
  * Google Docs / Slides / Sheets: their export URLs (works when shared as "Anyone with the link").
  * Direct file links (PDF, Word, PowerPoint, images, text): downloaded and processed like an upload.
  * Other pages: the main readable text (trafilatura) and the page title.

Anything that can't be read raises LinkError with a reason for the source card ("needs a login",
"no transcript", ...). Only http(s) URLs on public hosts are fetched."""
from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlencode, urlparse, urlunparse

import httpx

from .. import config


class LinkError(Exception):
    """A link that couldn't be read; the message is shown on the source card."""


@dataclass
class Fetched:
    source_type: str                 # web | web_pdf | youtube | gdoc | gslides | gsheet | web_file
    title: str
    text: str | None = None          # readable text, stored as a text upload
    file_bytes: bytes | None = None  # a document to process like an upload
    filename: str | None = None


# --- URL parsing ----------------------------------------------------------------------------

_YT_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_TRACKING = re.compile(r"^(utm_\w+|fbclid|gclid|mc_cid|mc_eid|igshid|ref_src|si)$", re.I)


def clean_url(raw: str) -> str:
    """Trim and add a scheme to a pasted URL; raise LinkError if it isn't a web address."""
    url = raw.strip().strip("<>\"'")
    if not url:
        raise LinkError("The link is empty.")
    if not re.match(r"^[a-z][a-z0-9+.-]*://", url, re.I):
        if re.match(r"^[a-z][a-z0-9+.-]*:(?!\d)", url, re.I):  # mailto:, javascript:, ... (but not host:port)
            raise LinkError("That doesn't look like a web link (it should start with http:// or https://).")
        url = "https://" + url
    p = urlparse(url)
    if p.scheme.lower() not in ("http", "https") or not p.hostname or "." not in p.hostname and p.hostname != "localhost":
        raise LinkError("That doesn't look like a web link (it should start with http:// or https://).")
    return url


def youtube_id(url: str) -> str | None:
    p = urlparse(url)
    host = (p.hostname or "").lower().removeprefix("www.").removeprefix("m.").removeprefix("music.")
    vid = None
    if host == "youtu.be":
        vid = p.path.strip("/").split("/")[0]
    elif host in ("youtube.com", "youtube-nocookie.com"):
        if p.path == "/watch":
            vid = (parse_qs(p.query).get("v") or [None])[0]
        else:
            m = re.match(r"^/(?:shorts|embed|live|v)/([^/?#]+)", p.path)
            vid = m.group(1) if m else None
    return vid if vid and _YT_ID.match(vid) else None


def google_file(url: str) -> tuple[str, str] | None:
    """(kind, file id) for Google Docs/Slides/Sheets/Drive links."""
    p = urlparse(url)
    host = (p.hostname or "").lower()
    if host == "docs.google.com":
        m = re.match(r"^/(document|presentation|spreadsheets)/d/([A-Za-z0-9_-]+)", p.path)
        if m:
            return {"document": "gdoc", "presentation": "gslides", "spreadsheets": "gsheet"}[m.group(1)], m.group(2)
    if host == "drive.google.com":
        m = re.match(r"^/file/d/([A-Za-z0-9_-]+)", p.path)
        if m:
            return "gdrive", m.group(1)
        fid = (parse_qs(p.query).get("id") or [None])[0]
        if fid:
            return "gdrive", fid
    return None


def normalize_url(url: str) -> str:
    """Canonical form for de-duplication: lowercase host without www., no fragment, no tracking
    parameters, sorted query, no trailing slash."""
    p = urlparse(clean_url(url))
    host = (p.hostname or "").lower().removeprefix("www.")
    if p.port and not (p.scheme == "http" and p.port == 80 or p.scheme == "https" and p.port == 443):
        host = f"{host}:{p.port}"
    query = sorted((k, v) for k, vs in parse_qs(p.query, keep_blank_values=True).items() if not _TRACKING.match(k) for v in vs)
    path = p.path.rstrip("/") or ""
    return urlunparse(("https" if p.scheme in ("http", "https") else p.scheme, host, path, "", urlencode(query), ""))


def dedupe_key(url: str) -> str:
    vid = youtube_id(url)
    if vid:
        return f"yt:{vid}"
    g = google_file(url)
    if g:
        return f"gfile:{g[1]}"
    return f"url:{normalize_url(url)}"


# --- Fetching ---------------------------------------------------------------------------------

def _is_private_host(host: str) -> bool:
    """True for localhost and private/link-local/reserved addresses (literal or resolved)."""
    host = host.strip("[]").lower()
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        return True
    try:
        addrs = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            addrs = [ipaddress.ip_address(info[4][0].split("%")[0]) for info in socket.getaddrinfo(host, None)]
        except (socket.gaierror, UnicodeError, ValueError):
            return False  # unresolvable: the request itself will fail with a clear message
    return any(a.is_private or a.is_loopback or a.is_link_local or a.is_reserved or a.is_multicast or a.is_unspecified
               for a in addrs)


async def _guard(request: httpx.Request) -> None:
    host = request.url.host
    if await asyncio.to_thread(is_private_host, host):
        raise LinkError("Links to this computer or your local network can't be added.")


is_private_host: Callable[[str], bool] = _is_private_host  # replaced in tests


def make_client(user_agent: str | None = None, transport: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={"User-Agent": user_agent or config.LINK_USER_AGENT, "Accept-Language": "en-US,en;q=0.9",
                 "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8"},
        timeout=config.LINK_TIMEOUT, follow_redirects=True, max_redirects=config.LINK_MAX_REDIRECTS,
        event_hooks={"request": [_guard]}, transport=transport,
    )


@dataclass
class Response:
    status: int
    url: str
    content_type: str
    headers: httpx.Headers
    body: bytes


async def _get(client: httpx.AsyncClient, url: str, **kw: Any) -> Response:
    limit = config.MAX_FILE_MB * 1024 * 1024
    try:
        async with client.stream("GET", url, **kw) as r:
            chunks: list[bytes] = []
            size = 0
            async for chunk in r.aiter_bytes():
                size += len(chunk)
                if size > limit:
                    raise LinkError(f"The linked file is larger than {config.MAX_FILE_MB} MB.")
                chunks.append(chunk)
            ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
            return Response(r.status_code, str(r.url), ctype, r.headers, b"".join(chunks))
    except LinkError:
        raise
    except httpx.TooManyRedirects:
        raise LinkError("The link redirects too many times.") from None
    except httpx.TimeoutException:
        raise LinkError(f"The site didn't respond within {config.LINK_TIMEOUT} seconds.") from None
    except httpx.ConnectError:
        raise LinkError("Couldn't connect to the site. Check the link and your internet connection.") from None
    except httpx.HTTPError as e:
        raise LinkError(f"The page couldn't be downloaded ({type(e).__name__}).") from None


def _status_error(status: int) -> LinkError:
    if status in (401, 407):
        return LinkError("This page needs you to log in, so the app can't read it. Download it and upload the file instead.")
    if status == 402:
        return LinkError("This page is behind a paywall. Download or copy it and upload the file instead.")
    if status == 403:
        return LinkError("The site blocked the app from reading this page. Save it as a PDF and upload the file instead.")
    if status in (404, 410):
        return LinkError("The page wasn't found (it may have moved or been deleted).")
    if status == 429:
        return LinkError("The site is limiting requests right now. Try again in a few minutes.")
    if status == 451:
        return LinkError("This page isn't available here for legal reasons.")
    return LinkError(f"The site returned an error (HTTP {status}).")


def _filename_from(resp: Response, fallback: str) -> str:
    cd = resp.headers.get("content-disposition", "")
    m = re.search(r"filename\*=(?:UTF-8'')?([^;]+)", cd, re.I) or re.search(r'filename="?([^";]+)"?', cd, re.I)
    if m:
        return unquote(m.group(1).strip().strip('"'))
    name = unquote(urlparse(resp.url).path.rstrip("/").rsplit("/", 1)[-1])
    return name or fallback


_FILE_TYPES = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "image/png": ".png",
    "image/jpeg": ".jpg",
}


def _as_file(resp: Response, fallback_name: str) -> Fetched | None:
    """A response that is a document we can process like an upload (by content type, magic bytes, or extension)."""
    ext = _FILE_TYPES.get(resp.content_type)
    if ext is None and resp.body[:5] == b"%PDF-":
        ext = ".pdf"
    if ext is None:
        path_ext = "." + urlparse(resp.url).path.rsplit(".", 1)[-1].lower() if "." in urlparse(resp.url).path else ""
        if path_ext in config.SUPPORTED_EXTENSIONS and config.SUPPORTED_EXTENSIONS[path_ext] in ("pdf", "docx", "pptx", "image") \
                and resp.content_type in ("application/octet-stream", "binary/octet-stream", ""):
            ext = path_ext
    if ext is None:
        return None
    name = _filename_from(resp, fallback_name)
    if not name.lower().endswith(ext) and not (ext == ".jpg" and name.lower().endswith(".jpeg")):
        name = f"{name}{ext}"
    title = re.sub(r"\.[a-z0-9]+$", "", name, flags=re.I) or fallback_name
    return Fetched(source_type="web_pdf" if ext == ".pdf" else "web_file", title=title, file_bytes=resp.body, filename=name)


def _decode(resp: Response) -> str:
    m = re.search(r"charset=([\w-]+)", resp.headers.get("content-type", ""), re.I)
    for enc in ([m.group(1)] if m else []) + ["utf-8", "cp1252"]:
        try:
            return resp.body.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return resp.body.decode("utf-8", "replace")


_LOGIN_PATH = re.compile(r"/(log-?in|sign-?in|signin|auth|sso|account/login|session/new)\b", re.I)


_DISPLAYSTYLE = re.compile(r"^\{\\displaystyle\s*(.*)\}$", re.S)


def _tex(src: str) -> str:
    src = " ".join(src.split())
    m = _DISPLAYSTYLE.match(src)
    return m.group(1).strip() if m else src


def math_to_tex(html: str) -> str:
    """Replace rendered math (MathML, Wikipedia's math spans, KaTeX, MathJax scripts) with $LaTeX$ text,
    which text extraction would otherwise drop."""
    if "<math" not in html and "katex" not in html and "math/tex" not in html:
        return html
    import lxml.html

    try:
        root = lxml.html.fromstring(html)
    except (ValueError, lxml.etree.ParserError):
        return html

    def replace(el, tex: str) -> None:
        if not tex:
            return
        new = lxml.html.Element("span")
        new.text = f" ${tex}$ "
        new.tail = el.tail
        el.getparent().replace(el, new) if el.getparent() is not None else None

    for el in root.xpath('//*[contains(concat(" ", normalize-space(@class), " "), " mwe-math-element ")]'):
        alt = el.xpath('.//math/@alttext') or el.xpath('.//img/@alt')
        replace(el, _tex(alt[0]) if alt else "")
    for el in root.xpath('//*[contains(concat(" ", normalize-space(@class), " "), " katex ")]'):
        ann = el.xpath('.//annotation[@encoding="application/x-tex"]/text()')
        replace(el, _tex(ann[0]) if ann else "")
    for el in root.xpath("//math"):
        tex = el.get("alttext") or "".join(el.xpath('.//annotation[@encoding="application/x-tex"]/text()'))
        replace(el, _tex(tex))
    for el in root.xpath('//script[starts-with(@type, "math/tex")]'):
        replace(el, _tex(el.text or ""))
    return lxml.html.tostring(root, encoding="unicode")


def extract_html(html: str, url: str) -> tuple[str, str]:
    """(title, main text as Markdown) of a web page. Math is kept as $LaTeX$."""
    import trafilatura

    html = math_to_tex(html)
    text = trafilatura.extract(html, url=url, include_tables=True, include_links=False, include_images=False,
                               include_comments=False, output_format="markdown", favor_recall=True) or ""
    title = ""
    try:
        meta = trafilatura.extract_metadata(html, default_url=url)
        title = (meta.title or "") if meta else ""
    except Exception:  # noqa: BLE001 - metadata is best effort
        title = ""
    if not title:
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
        title = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
    # Citation markers ("<sup>[3]</sup>", "[citation needed]") are noise in study material.
    text = re.sub(r"<sup>\\?\[[^\]]{1,30}\\?\]</sup>|\\?\[(?:citation needed|clarification needed)\\?\]", "", text)
    # Markdown output escapes _ * # inside the $LaTeX$ too (T\_c); undo that within math only.
    text = re.sub(r"\$[^$\n]{1,400}\$", lambda m: re.sub(r"\\([_*#])", r"\1", m.group(0)), text)
    return title, text.strip()


async def _fetch_web(client: httpx.AsyncClient, url: str) -> Fetched:
    resp = await _get(client, url)
    if resp.status == 403:
        # Some sites refuse non-browser agents; try once more as a browser before giving up.
        resp = await _get(client, url, headers={"User-Agent": config.BROWSER_USER_AGENT})
    if resp.status >= 400:
        raise _status_error(resp.status)
    host = urlparse(resp.url).hostname or ""
    if (resp.url != url and _LOGIN_PATH.search(urlparse(resp.url).path)) or host.startswith(("accounts.", "login.")):
        raise LinkError("This page redirected to a login screen, so the app can't read it. Download it and upload the file instead.")
    fallback = urlparse(resp.url).hostname or "Link"
    as_file = _as_file(resp, fallback)
    if as_file:
        return as_file
    if resp.content_type in ("text/plain", "text/markdown", "text/x-markdown", "text/csv"):
        text = _decode(resp)
        if not text.strip():
            raise LinkError("The linked file is empty.")
        return Fetched("web", _filename_from(resp, fallback), text=text)
    if resp.content_type not in ("text/html", "application/xhtml+xml", ""):
        raise LinkError(f"This link is a file type the app can't read ({resp.content_type}).")
    title, text = await asyncio.to_thread(extract_html, _decode(resp), resp.url)
    if len(text) < config.LINK_MIN_TEXT_CHARS:
        raise LinkError("Couldn't find readable text on this page. It may need a login, be behind a paywall, or only "
                        "load with JavaScript. Save it as a PDF and upload the file instead.")
    return Fetched("web", title or fallback, text=f"# {title}\n\nSource: {resp.url}\n\n{text}" if title else text)


# --- Google files -----------------------------------------------------------------------------

_GOOGLE_EXPORT = {
    "gdoc": ("https://docs.google.com/document/d/{id}/export?format=txt", "Google Doc"),
    "gslides": ("https://docs.google.com/presentation/d/{id}/export/pptx", "Google Slides"),
    "gsheet": ("https://docs.google.com/spreadsheets/d/{id}/export?format=csv", "Google Sheet"),
    "gdrive": ("https://drive.google.com/uc?export=download&id={id}", "Google Drive file"),
}
NOT_PUBLIC = ("This Google file isn't shared publicly, so the app can't read it. In Google, choose Share → General "
              "access → \"Anyone with the link\", or download it and upload the file instead.")


async def _fetch_google(client: httpx.AsyncClient, kind: str, file_id: str) -> Fetched:
    template, label = _GOOGLE_EXPORT[kind]
    resp = await _get(client, template.format(id=file_id))
    host = urlparse(resp.url).hostname or ""
    if resp.status in (401, 403, 404) or host.startswith("accounts.google.") or \
            (kind != "gdrive" and resp.content_type == "text/html"):
        raise LinkError(NOT_PUBLIC)
    if resp.status >= 400:
        raise _status_error(resp.status)
    name = _filename_from(resp, label)
    title = re.sub(r"\.(txt|pptx|csv|pdf|docx)$", "", name, flags=re.I) or label
    if kind == "gslides":
        return Fetched("gslides", title, file_bytes=resp.body, filename=f"{title}.pptx")
    if kind == "gdrive":
        if resp.content_type == "text/html":
            raise LinkError("Google Drive didn't return the file (it may be private or too large to scan for viruses). "
                            "Download it and upload the file instead.")
        as_file = _as_file(resp, title)
        if not as_file:
            raise LinkError("This Google Drive file isn't a type the app can read (PDF, Word, PowerPoint, or images).")
        return as_file
    text = _decode(resp).lstrip("﻿")
    if not text.strip():
        raise LinkError(f"This {label} is empty.")
    return Fetched(kind, title, text=f"# {title}\n\n{text}")


# --- YouTube ----------------------------------------------------------------------------------

async def youtube_oembed(client: httpx.AsyncClient, video_id: str) -> dict[str, Any] | None:
    """Title/channel/thumbnail of a public video, or None if it doesn't exist or can't be embedded."""
    try:
        r = await client.get("https://www.youtube.com/oembed",
                             params={"url": f"https://www.youtube.com/watch?v={video_id}", "format": "json"})
    except httpx.HTTPError:
        raise LinkError("Couldn't reach YouTube. Check your internet connection.") from None
    if r.status_code != 200:
        return None
    try:
        return r.json()
    except ValueError:
        return None


def _fmt_ts(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def fetch_transcript(video_id: str) -> str:
    """Transcript text with a [m:ss] marker about every 30 seconds. Raises LinkError if there isn't one."""
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api import _errors as yt_errors

    try:
        listing = YouTubeTranscriptApi().list(video_id)
        transcripts = list(listing)
        if not transcripts:
            raise LinkError("This video has no transcript, so it can't be used as material.")
        try:
            chosen = listing.find_transcript(["en", "en-US", "en-GB"])
        except yt_errors.NoTranscriptFound:
            manual = [t for t in transcripts if not t.is_generated]
            chosen = (manual or transcripts)[0]
        fetched = chosen.fetch()
    except LinkError:
        raise
    except (yt_errors.TranscriptsDisabled, yt_errors.NoTranscriptFound):
        raise LinkError("This video has no transcript available (captions are turned off), so it can't be used as "
                        "material. Look for a version with captions, or add notes about it instead.") from None
    except yt_errors.VideoUnavailable:
        raise LinkError("This YouTube video is unavailable (private, removed, or region-locked).") from None
    except yt_errors.CouldNotRetrieveTranscript as e:
        reason = type(e).__name__
        if "Blocked" in reason:
            raise LinkError("YouTube is blocking transcript requests from this network right now. Try again later.") from None
        if "Age" in reason:
            raise LinkError("This video is age-restricted, so its transcript can't be read.") from None
        raise LinkError("This video's transcript couldn't be read.") from None
    lines: list[str] = []
    next_mark = 0.0
    for snip in fetched.snippets:
        text = snip.text.replace("\n", " ").strip()
        if not text:
            continue
        if snip.start >= next_mark:
            lines.append(f"\n[{_fmt_ts(snip.start)}] ")
            next_mark = snip.start + 30
        lines.append(text + " ")
    out = "".join(lines).strip()
    if not out:
        raise LinkError("This video's transcript is empty.")
    lang = f" (transcript language: {chosen.language})" if not chosen.language_code.startswith("en") else ""
    return out + lang


async def _fetch_youtube(client: httpx.AsyncClient, video_id: str,
                         transcript: Callable[[str], str]) -> Fetched:
    meta = await youtube_oembed(client, video_id)
    if meta is None:
        raise LinkError("This YouTube video doesn't exist or is private.")
    title = meta.get("title") or "YouTube video"
    channel = meta.get("author_name") or ""
    text = await asyncio.to_thread(transcript, video_id)
    header = f"# {title}\n\nYouTube video{f' by {channel}' if channel else ''}: https://www.youtube.com/watch?v={video_id}\n\n## Transcript\n"
    return Fetched("youtube", title, text=header + text)


# --- Entry point ------------------------------------------------------------------------------

async def fetch_link(url: str, client: httpx.AsyncClient | None = None,
                     transcript: Callable[[str], str] | None = None) -> Fetched:
    url = clean_url(url)
    own = client is None
    client = client or make_client()
    try:
        vid = youtube_id(url)
        if vid:
            return await _fetch_youtube(client, vid, transcript or fetch_transcript)
        g = google_file(url)
        if g:
            return await _fetch_google(client, *g)
        return await _fetch_web(client, url)
    finally:
        if own:
            await client.aclose()
