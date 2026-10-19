"""A fake internet for tests: routes requests to handlers by URL prefix (httpx.MockTransport), used for
link reading (services/linkfetch) and YouTube calls (services/youtube)."""
from __future__ import annotations

import json
from typing import Callable

import httpx
import pytest

from sage.services import linkfetch, youtube

Handler = Callable[[httpx.Request], httpx.Response]


class FakeWeb:
    def __init__(self):
        self.routes: list[tuple[str, Handler]] = []
        self.requests: list[httpx.Request] = []

    def add(self, prefix: str, handler: Handler | httpx.Response) -> None:
        """Most recently added matching prefix wins."""
        fn = handler if callable(handler) else (lambda _req, r=handler: r)
        self.routes.insert(0, (prefix, fn))

    def html(self, prefix: str, body: str, status: int = 200) -> None:
        self.add(prefix, httpx.Response(status, text=body, headers={"content-type": "text/html; charset=utf-8"}))

    def json(self, prefix: str, data, status: int = 200) -> None:
        self.add(prefix, httpx.Response(status, text=json.dumps(data), headers={"content-type": "application/json"}))

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        for prefix, fn in self.routes:
            if url.startswith(prefix):
                return fn(request)
        return httpx.Response(404, text="not found")

    def count(self, prefix: str) -> int:
        return sum(1 for r in self.requests if str(r.url).startswith(prefix))

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)


ARTICLE = """<html><head><title>The First Law of Thermodynamics</title></head><body>
<nav>Home | About</nav>
<article><h1>The First Law of Thermodynamics</h1>
<p>The first law of thermodynamics is a version of the law of conservation of energy, adapted for
thermodynamic processes. It states that the change in internal energy of a closed system equals the heat
supplied to the system minus the work done by the system on its surroundings.</p>
<p>For an ideal gas undergoing an isothermal process, the internal energy does not change, so all of the
heat added is converted into work. In an adiabatic process no heat is exchanged, so the work done comes
entirely from the internal energy of the gas, and its temperature falls as it expands.</p>
<p>Enthalpy, defined as internal energy plus the product of pressure and volume, is convenient for
processes at constant pressure, where the heat transferred equals the change in enthalpy.</p>
</article><footer>Copyright</footer></body></html>"""


def oembed_ok(video_id: str, title: str = "A video", author: str = "A Channel") -> httpx.Response:
    return httpx.Response(200, json={"title": title, "author_name": author,
                                     "thumbnail_url": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"})


@pytest.fixture
def web(monkeypatch):
    fake = FakeWeb()
    real_make = linkfetch.make_client

    monkeypatch.setattr(linkfetch, "make_client", lambda user_agent=None, transport=None: real_make(user_agent, fake.transport()))
    monkeypatch.setattr(linkfetch, "is_private_host", lambda host: host in ("127.0.0.1", "localhost", "10.0.0.5"))
    monkeypatch.setattr(youtube, "http_client", lambda: httpx.AsyncClient(transport=fake.transport()))
    monkeypatch.setattr(linkfetch, "fetch_transcript", lambda vid: f"[0:00] transcript of {vid} about heat and work")

    # Every video exists unless a test says otherwise.
    def oembed(req: httpx.Request) -> httpx.Response:
        vid = str(req.url.params.get("url", "")).rsplit("v=", 1)[-1]
        return oembed_ok(vid, title=f"Title {vid}")

    fake.add("https://www.youtube.com/oembed", oembed)
    fake.add("https://www.youtube.com/watch?v=", lambda req: httpx.Response(200, text='"lengthSeconds":"600"'))
    return fake
