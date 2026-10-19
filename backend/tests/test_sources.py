"""Sources: URL normalisation and de-duplication of files and links, background link reading,
and "Couldn't read" sources that never sink a Study Set."""
from __future__ import annotations

import httpx
import pytest

from sage.services import linkfetch as L

from .conftest import wait_for
from .web_mock import ARTICLE


@pytest.mark.parametrize("a,b", [
    ("https://www.Example.com/notes/", "http://example.com/notes"),
    ("https://example.com/a?utm_source=x&b=2&fbclid=1#section", "https://example.com/a?b=2"),
    ("https://example.com/a?b=2&c=3", "https://example.com/a?c=3&b=2"),
    ("https://youtu.be/NyOYW07-L5g", "https://www.youtube.com/watch?v=NyOYW07-L5g&t=30s&list=PL1"),
    ("https://m.youtube.com/shorts/NyOYW07-L5g", "https://www.youtube.com/embed/NyOYW07-L5g"),
    ("https://docs.google.com/document/d/abc/edit", "https://docs.google.com/document/d/abc/view?usp=sharing"),
])
def test_same_dedupe_key(a, b):
    assert L.dedupe_key(a) == L.dedupe_key(b)


@pytest.mark.parametrize("a,b", [
    ("https://example.com/a", "https://example.com/b"),
    ("https://example.com/a?page=1", "https://example.com/a?page=2"),
    ("https://youtu.be/NyOYW07-L5g", "https://youtu.be/p_A25qLUe4w"),
])
def test_different_dedupe_key(a, b):
    assert L.dedupe_key(a) != L.dedupe_key(b)


def add_links(client, urls, **scope):
    r = client.post("/api/sources/links", json={"urls": urls, **scope})
    assert r.status_code == 200, r.text
    return r.json()


def wait_ready(client, ids):
    def poll():
        rows = client.get("/api/sources", params={"ids": ",".join(ids)}).json()
        return rows if all(r["status"] != "processing" for r in rows) else None
    return wait_for(poll)


def test_links_are_read_in_background_and_deduplicated(client, web):
    web.html("https://example.com/thermo", ARTICLE)
    first = add_links(client, ["https://example.com/thermo", "https://youtu.be/NyOYW07-L5g"], draft_id="d1")
    assert [s["status"] for s in first] == ["processing", "processing"]
    rows = wait_ready(client, [s["id"] for s in first])
    assert [r["status"] for r in rows] == ["ready", "ready"]
    assert rows[0]["title"] == "The First Law of Thermodynamics" and rows[0]["source_type"] == "web"
    assert rows[1]["source_type"] == "youtube" and rows[1]["char_count"] > 0

    again = add_links(client, ["http://www.example.com/thermo/", "https://www.youtube.com/watch?v=NyOYW07-L5g&t=5"], draft_id="d1")
    assert all(s["duplicate"] for s in again)
    assert [s["id"] for s in again] == [s["id"] for s in first]
    # A different draft (another setup screen) can add the same link.
    assert not add_links(client, ["https://example.com/thermo"], draft_id="d2")[0]["duplicate"]


def test_bad_link_fails_alone(client, web):
    web.html("https://example.com/thermo", ARTICLE)
    web.html("https://example.com/paywalled", "pay", status=402)
    out = add_links(client, ["https://example.com/thermo", "https://example.com/paywalled", "mailto:x@y.z"], draft_id="d")
    assert out[2]["status"] == "failed" and out[2]["id"] is None
    rows = wait_ready(client, [out[0]["id"], out[1]["id"]])
    assert rows[0]["status"] == "ready"
    assert rows[1]["status"] == "failed" and "paywall" in rows[1]["error"]["message"]

    # The set is created and broken down from the readable source only.
    s = client.post("/api/sets", json={"prompt": "Thermo", "source_ids": [out[0]["id"], out[1]["id"]]}).json()
    view = wait_for(lambda: (lambda v: v if v["breakdown"]["status"] == "ready" else None)(client.get(f"/api/sets/{s['id']}").json()))
    assert [x["status"] for x in view["sources"]] == ["ready", "failed"]
    assert view["breakdown"]["unreadable_sources"] == ["https://example.com/paywalled"]


def test_duplicate_files(client):
    data = b"Enthalpy is H = U + PV. " * 30
    a = client.post("/api/sources/files", files={"file": ("notes.txt", data, "text/plain")}, data={"draft_id": "d"}).json()
    b = client.post("/api/sources/files", files={"file": ("copy of notes.txt", data, "text/plain")}, data={"draft_id": "d"}).json()
    c = client.post("/api/sources/files", files={"file": ("other.txt", data + b"!", "text/plain")}, data={"draft_id": "d"}).json()
    assert not a["duplicate"] and b["duplicate"] and b["id"] == a["id"] and not c["duplicate"]


def test_attaching_drops_sources_the_set_already_has(client, web):
    data = b"Carnot cycle notes. " * 40
    a = client.post("/api/sources/files", files={"file": ("a.txt", data, "text/plain")}, data={"draft_id": "d"}).json()
    s = client.post("/api/sets", json={"prompt": "x", "source_ids": [a["id"]]}).json()
    # The same file added again on the set's Append panel is a duplicate.
    dup = client.post("/api/sources/files", files={"file": ("a2.txt", data, "text/plain")}, data={"set_id": s["id"]}).json()
    assert dup["duplicate"] and dup["id"] == a["id"]


def test_remove_and_retry(client, web):
    calls = {"n": 0}

    def flaky(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503 if calls["n"] == 1 else 200, text=ARTICLE, headers={"content-type": "text/html"})
    web.add("https://example.com/flaky", flaky)
    src = add_links(client, ["https://example.com/flaky"], draft_id="d")[0]
    assert wait_ready(client, [src["id"]])[0]["status"] == "failed"
    assert client.post(f"/api/sources/{src['id']}/retry").json()["status"] == "processing"
    assert wait_ready(client, [src["id"]])[0]["status"] == "ready"
    assert client.delete(f"/api/sources/{src['id']}").json() == {"ok": True}
    assert client.get("/api/sources", params={"ids": src["id"]}).json() == []
