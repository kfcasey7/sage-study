"""YouTube: Data API parsing and caching, oEmbed verification, the no-key WebSearch fallback, ranking
validation (no invented ids), playlists, and "Find video" during a quiz (all HTTP mocked)."""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from sage import secrets
from sage.errors import AppError
from sage.services import youtube as Y

from .conftest import cli_result, wait_for
from .test_api import correct_answer, next_q
from .test_breakdown import make_set

IDS = ["NyOYW07-L5g", "p_A25qLUe4w", "Bz6vexpZItw", "mrSkqiwphzI", "mNnmcXUJQGE", "4i1MUWJoI0U", "aaaaaaaaaaa", "bbbbbbbbbbb"]


@pytest.mark.parametrize("iso,seconds", [("PT4M13S", 253), ("PT1H2M3S", 3723), ("PT45S", 45), ("P1DT1S", 86401),
                                         ("PT10M", 600), ("", None), ("P0D", 0), ("bogus", None)])
def test_parse_iso_duration(iso, seconds):
    assert Y.parse_iso_duration(iso) == seconds


def test_video_ids_in_search_text():
    text = ('Links: [{"url":"https://www.youtube.com/watch?v=NyOYW07-L5g"},{"url":"https://youtu.be/p_A25qLUe4w?t=3"},'
            '{"url":"https://www.youtube.com/watch?feature=share&v=Bz6vexpZItw"},{"url":"https://www.youtube.com/@channel"}]')
    assert Y.video_ids_in([text]) == {"NyOYW07-L5g", "p_A25qLUe4w", "Bz6vexpZItw"}


def search_json(ids):
    return {"items": [{"id": {"kind": "youtube#video", "videoId": v},
                       "snippet": {"title": f"T {v}", "channelTitle": "Edu", "description": "d", "publishedAt": "2020-01-01"}}
                      for v in ids]}


def videos_json(ids, duration="PT8M20S"):
    return {"items": [{"id": v, "snippet": {"title": f"T {v}", "channelTitle": "Edu Channel"},
                       "contentDetails": {"duration": duration}, "statistics": {"viewCount": "12345"}} for v in ids]}


def test_api_search_parses_and_caches(web):
    web.json("https://www.googleapis.com/youtube/v3/search", search_json(IDS[:3]))

    async def run():
        async with Y.http_client() as c:
            a = await Y.api_search(c, "KEY", "first law  explained")
            b = await Y.api_search(c, "KEY", "First law explained")  # same query, normalised: cached
            return a, b
    a, b = asyncio.run(run())
    assert [x["video_id"] for x in a] == IDS[:3] and a == b
    assert web.count("https://www.googleapis.com/youtube/v3/search") == 1
    req = next(r for r in web.requests if "search" in str(r.url))
    assert req.url.params["type"] == "video" and req.url.params["videoEmbeddable"] == "true" and req.url.params["key"] == "KEY"


def test_api_details_and_quota_error(web):
    web.json("https://www.googleapis.com/youtube/v3/videos", videos_json(IDS[:2]))

    async def details():
        async with Y.http_client() as c:
            return await Y.api_details(c, "KEY", IDS[:2])
    d = asyncio.run(details())
    assert d[IDS[0]] == {"title": f"T {IDS[0]}", "channel": "Edu Channel", "duration_s": 500, "views": 12345}

    web.json("https://www.googleapis.com/youtube/v3/search",
             {"error": {"code": 403, "message": "quota", "errors": [{"reason": "quotaExceeded"}]}}, status=403)

    async def search():
        async with Y.http_client() as c:
            return await Y.api_search(c, "KEY", "anything new")
    with pytest.raises(AppError) as e:
        asyncio.run(search())
    assert e.value.code == "youtube_quota"


def test_oembed_failures_are_dropped(web):
    web.add("https://www.youtube.com/oembed", lambda req: httpx.Response(404) if "aaaaaaaaaaa" in str(req.url)
            else httpx.Response(200, json={"title": "ok", "author_name": "Ch"}))
    ranked = [{"video_id": "aaaaaaaaaaa", "reason": "r"}, {"video_id": IDS[0], "reason": "r"}, {"video_id": IDS[1], "reason": "r"}]

    async def run():
        async with Y.http_client() as c:
            return await Y._finish(c, ranked, 1, with_api=False)
    shown, spares = asyncio.run(run())
    assert [v["video_id"] for v in shown] == [IDS[0]]
    assert shown[0]["channel"] == "Ch" and shown[0]["duration_s"] == 600  # from the watch page
    assert [v["video_id"] for v in spares] == [IDS[1]]


def test_search_validator_keeps_only_ids_from_search_results():
    validate = Y.validate_search({"s1"})
    data = {"targets": [{"key": "s1", "videos": [
        {"url": f"https://www.youtube.com/watch?v={IDS[0]}", "title": "real", "reason": "r"},
        {"url": "https://www.youtube.com/watch?v=madeUpId123", "title": "invented", "reason": "r"},
        {"url": "https://vimeo.com/123", "title": "wrong site", "reason": "r"},
    ]}, {"key": "unknown", "videos": []}]}
    out = validate(data, [f'Links: [{{"url": "https://www.youtube.com/watch?v={IDS[0]}"}}]'])
    assert [v["video_id"] for v in out["s1"]] == [IDS[0]]


def test_rank_validator_rejects_unknown_ids():
    validate = Y.validate_rank({"s1": [{"video_id": IDS[0]}, {"video_id": IDS[1]}]})
    assert validate({"targets": [{"key": "s1", "picks": [{"video_id": IDS[1], "reason": "x"}]}]})["s1"][0]["video_id"] == IDS[1]
    with pytest.raises(ValueError, match="not in the candidate"):
        validate({"targets": [{"key": "s1", "picks": [{"video_id": "inventedXYZ", "reason": "x"}]}]})


def test_find_videos_with_api_key(web, fake_claude):
    secrets.set_youtube_key("AIzaTESTKEY-1234")
    web.json("https://www.googleapis.com/youtube/v3/search", search_json(IDS[:5]))
    web.json("https://www.googleapis.com/youtube/v3/videos", videos_json(IDS[:5]))
    # The rank call first tries an invented id; the validator sends it back, and the retry is used.
    fake_claude.queue("video_rank", lambda req: {"targets": [{"key": "s1", "picks": [{"video_id": "inventedXYZ", "reason": "x"}]}]})
    out = asyncio.run(Y.find_videos([{"key": "s1", "title": "Carnot cycle", "description": ""}], per_target=3))
    shown, spares = out["s1"]
    assert [v["video_id"] for v in shown] == IDS[:3] and [v["video_id"] for v in spares] == IDS[3:5]
    assert shown[0]["duration_s"] == 500 and shown[0]["channel"] == "Edu Channel"
    assert fake_claude.purposes().count("video_rank") == 2 and "video_search" not in fake_claude.purposes()
    assert web.count("https://www.youtube.com/watch?v=") == 0  # durations come from the API


def test_find_videos_without_key_uses_websearch_only(web, fake_claude):
    def search(req):
        assert req.tools == ["WebSearch"] and not req.files
        payload = {"targets": [{"key": "s1", "videos": [
            {"url": "https://www.youtube.com/watch?v=inventedXYZ", "title": "not in results", "reason": "x"},
            {"url": f"https://youtu.be/{IDS[2]}", "title": "real", "reason": "fits"}]}]}
        return {**cli_result(payload), "_search_results": [f'Links: [{{"url": "https://www.youtube.com/watch?v={IDS[2]}"}}]']}
    fake_claude.queue("video_search", search)
    out = asyncio.run(Y.find_videos([{"key": "s1", "title": "Carnot cycle", "description": ""}], per_target=3))
    assert [v["video_id"] for v in out["s1"][0]] == [IDS[2]]
    from sage import llm_client
    args = llm_client.build_args("claude", fake_claude.calls[-1]["req"])
    assert args[args.index("--tools") + 1] == "WebSearch" and args[args.index("--allowedTools") + 1] == "WebSearch"
    assert "--restricted" in args and "stream-json" in args


def test_playlist_build_watch_replace_more(client, fake_claude, web):
    view = make_set(client)
    alpha, beta = view["subtopics"]

    def search(req):
        payload = {"targets": [
            {"key": alpha["id"], "videos": [{"url": f"https://youtu.be/{v}", "title": v, "reason": "fits"}
                                            for v in IDS[:3] + IDS[6:8]]},
            # Overlaps Alpha's picks: a video is only shown once in a playlist.
            {"key": beta["id"], "videos": [{"url": f"https://youtu.be/{v}", "title": v, "reason": "fits"} for v in IDS[2:6]]}]}
        return {**cli_result(payload), "_search_results": [" ".join(f"https://www.youtube.com/watch?v={v}" for v in IDS)]}
    fake_claude.queue("video_search", search)
    p = client.post(f"/api/sets/{view['id']}/playlists", json={"subtopic_ids": [alpha["id"], beta["id"]]}).json()
    p = wait_for(lambda: (lambda r: r if r["status"] != "generating" else None)(client.get(f"/api/playlists/{p['id']}").json()))
    assert p["status"] == "ready" and p["mode"] == "websearch"
    assert [g["name"] for g in p["groups"]] == ["Alpha", "Beta"]
    assert [[v["video_id"] for v in g["videos"]] for g in p["groups"]] == [IDS[:3], IDS[3:6]]
    first = p["groups"][0]["videos"][0]
    assert first["thumbnail"].startswith("https://i.ytimg.com/vi/") and first["reason"] and first["duration_s"] == 600
    all_ids = [v["video_id"] for g in p["groups"] for v in g["videos"]]
    assert p["youtube_playlist_url"] == "https://www.youtube.com/watch_videos?video_ids=" + ",".join(dict.fromkeys(all_ids))

    assert client.put(f"/api/playlist-items/{first['id']}", json={"watched": True}).json()["watched"]
    assert client.get(f"/api/playlists/{p['id']}").json()["groups"][0]["videos"][0]["watched"]

    calls = len(fake_claude.calls)
    group = p["groups"][0]
    assert group["spares_left"] >= 1
    r = client.post(f"/api/playlist-items/{group['videos'][-1]['id']}/replace").json()
    assert len(fake_claude.calls) == calls  # a spare was used: no new search
    new_ids = [v["video_id"] for v in r["groups"][0]["videos"]]
    assert group["videos"][-1]["video_id"] not in new_ids and len(new_ids) == len(group["videos"])

    r = client.post(f"/api/playlists/{p['id']}/more", json={"subtopic_id": alpha["id"]})
    assert r.status_code in (200, 404), r.text  # 404 = no more videos left anywhere
    sets = client.get(f"/api/sets/{view['id']}").json()
    assert sets["playlists"][0]["id"] == p["id"] and sets["playlists"][0]["watched"] == 1


def test_find_video_during_quiz_is_recorded_as_help(client, fake_claude, web):
    view = make_set(client)
    s = client.post(f"/api/sets/{view['id']}/quiz", json={"subtopic_ids": [view["subtopics"][0]["id"]],
                                                          "types": ["multiple_choice"], "count": 2}).json()
    q = next_q(client, s["id"])["question"]
    found = client.post(f"/api/questions/{q['id']}/videos").json()
    assert found["used_before_answer"] and 1 <= len(found["videos"]) <= 3
    search_prompt = fake_claude.calls[-1]["req"].prompt
    payload = json.loads(json.dumps(__import__("sage.services.sessions", fromlist=["x"]).load_question(q["id"])["payload"]))
    assert payload["prompt"][:20] in search_prompt and str(payload["correct_index"]) not in search_prompt.split("<target")[0][-5:]
    # Asking again returns the same videos without another search
    n = len(fake_claude.calls)
    assert client.post(f"/api/questions/{q['id']}/videos").json()["videos"] == found["videos"]
    assert len(fake_claude.calls) == n

    client.post(f"/api/questions/{q['id']}/answer", json={"response": correct_answer(q["id"]), "confidence": "high", "skipped": False})
    q2 = next_q(client, s["id"])["question"]
    client.post(f"/api/questions/{q2['id']}/answer", json={"response": correct_answer(q2["id"]), "confidence": "high", "skipped": False})
    res = client.post(f"/api/sessions/{s['id']}/finish").json()
    helped = {x["id"]: x["used_video_help"] for x in res["questions"]}
    assert helped == {q["id"]: True, q2["id"]: False}
    assert res["mastery"]["overall"]["score"] == 100  # help doesn't change the grade


def test_youtube_key_settings(client, web):
    assert client.get("/api/settings/youtube-key").json() == {"set": False, "last4": None, "mode": "websearch"}
    assert client.put("/api/settings/youtube-key", json={"key": "short"}).status_code == 400
    web.json("https://www.googleapis.com/youtube/v3/videos", {"error": {"code": 400, "message": "API key not valid.",
                                                                        "errors": [{"reason": "badRequest"}]}}, status=400)
    r = client.put("/api/settings/youtube-key", json={"key": "AIzaBAD0000000000000000000000000000000"})
    assert r.status_code >= 400 and r.json()["error"]["code"] == "youtube_key_invalid"
    web.json("https://www.googleapis.com/youtube/v3/videos", {"items": [{"id": "jNQXAC9IVRw"}]})
    ok = client.put("/api/settings/youtube-key", json={"key": "AIzaGOOD000000000000000000000000000wxyz"}).json()
    assert ok == {"set": True, "last4": "wxyz", "mode": "api"}
    assert "AIzaGOOD" not in json.dumps(client.get("/api/settings").json())
    assert client.delete("/api/settings/youtube-key").json()["set"] is False


def test_open_url_only_youtube(client, monkeypatch):
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url) or True)
    assert client.post("/api/open-url", json={"url": "https://www.youtube.com/watch?v=NyOYW07-L5g"}).json() == {"ok": True}
    assert client.post("/api/open-url", json={"url": "https://evil.example.com/"}).status_code == 400
    assert client.post("/api/open-url", json={"url": "file:///C:/Windows/system32/calc.exe"}).status_code == 400
    assert opened == ["https://www.youtube.com/watch?v=NyOYW07-L5g"]
