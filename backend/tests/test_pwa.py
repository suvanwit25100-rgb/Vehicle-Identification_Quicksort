"""The installable app: manifest, icons, service worker, offline page."""
import io
import json
import re
from pathlib import Path

import pytest
from PIL import Image

from .test_case_export import client  # noqa: F401  (fixture)

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


def test_the_manifest_is_complete_and_its_icons_are_real_pictures_of_the_right_size(client):
    r = client.get("/manifest.webmanifest")
    assert r.status_code == 200 and "json" in r.headers["content-type"] and r.headers["cache-control"] == "no-cache"
    m = r.json()
    assert m["display"] == "standalone" and m["start_url"] == "/report-issue/" and m["scope"] == "/" and m["name"] and m["short_name"] == "ExLex"
    assert {i["sizes"] for i in m["icons"]} >= {"192x192", "512x512"} and any(i.get("purpose") == "maskable" for i in m["icons"])
    for i in m["icons"]:
        img = client.get(i["src"])
        assert img.status_code == 200 and img.headers["content-type"] == "image/png", i["src"]
        w, h = Image.open(io.BytesIO(img.content)).size
        assert f"{w}x{h}" == i["sizes"], i["src"]
    assert all(client.get(s["url"]).status_code == 200 for s in m["shortcuts"])


def test_the_service_worker_is_served_fresh_and_precaches_only_files_that_exist(client):
    r = client.get("/sw.js")
    assert r.status_code == 200 and "javascript" in r.headers["content-type"] and r.headers["cache-control"] == "no-cache"
    shell = re.search(r"const SHELL = \[(.*?)\];", r.text, re.S).group(1)
    paths = re.findall(r'"([^"]+)"', shell)
    assert len(paths) >= 8
    for p in paths:
        assert client.get(p).status_code == 200, p


def test_the_service_worker_never_caches_api_or_officer_pages_or_writes():
    sw = (STATIC / "sw.js").read_text()
    for needle in ('url.pathname.startsWith("/api/")', 'startsWith("/officer")', 'startsWith("/desk")', 'req.method !== "GET"', "url.origin !== location.origin"):
        assert needle in sw, needle
    shell = re.search(r"const SHELL = \[(.*?)\];", sw, re.S).group(1)
    assert "/api/" not in shell and "/officer" not in shell and "/desk" not in shell


@pytest.mark.parametrize("page", ["/", "/report-issue/", "/status/"])
def test_the_citizen_pages_are_installable(client, page):
    html = client.get(page).text
    assert 'rel="manifest" href="/manifest.webmanifest"' in html and 'rel="apple-touch-icon"' in html and 'theme-color' in html and "/pwa.js" in html


def test_the_officer_portal_is_not_part_of_the_app(client):
    assert "pwa.js" not in client.get("/officer/").text and "manifest" not in client.get("/officer/").text


def test_the_offline_page_is_plain_and_honest(client):
    r = client.get("/offline.html")
    assert r.status_code == 200 and "offline" in r.text.lower() and "nothing is lost or half-sent" in r.text and "<script" not in r.text


def test_the_service_worker_behaves_in_a_fake_browser():
    """Runs sw.js in Node with a fake cache and network: what it caches, what it leaves alone, what it does offline."""
    import shutil
    import subprocess

    if not shutil.which("node"):
        pytest.skip("node is not installed")
    out = subprocess.run(["node", str(Path(__file__).parent / "sw_harness.js"), str(STATIC / "sw.js")], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    r = json.loads(out.stdout)
    assert "/report-issue/" in r["precached"] and "/offline.html" in r["precached"] and "/ui.css" in r["precached"]
    for left_alone in ("api", "officer", "desk", "sw", "post", "crossSite"):
        assert r[left_alone] == {"handled": False}, left_alone                       # the worker does not touch these at all
    assert r["navOnline"]["body"].startswith("live:")                                  # online, pages come from the network
    assert r["navOffline"]["body"].startswith("live:") or r["navOffline"]["body"].startswith("shell:")     # offline, a page visited before is served from the shell cache
    assert "shell:/offline.html" == r["navOfflineUnvisited"]["body"]                   # a page never visited gives the honest offline page
    assert r["assetOffline"]["body"].startswith("shell:") or r["assetOffline"]["body"].startswith("live:")
    assert not any(p.startswith("/api/") or p.startswith("/officer") or p.startswith("/desk") for p in r["cachedPaths"])
    assert r["cachesAfterActivate"] == ["exlex-shell-v1"]                              # old caches are cleaned up
