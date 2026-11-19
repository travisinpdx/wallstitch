# SPDX-FileCopyrightText: 2026 Travis Estill <immyouany@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

import json
from urllib.parse import parse_qs, urlparse

import pytest

from wallstitch import commons, wallhaven
from wallstitch.cli import _filters_from, build_parser
from wallstitch.commons import Candidate
from wallstitch.wallhaven import SearchFilters


def query_of(url):
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


def page(index, title, w, h, size=10_000_000):
    return {"index": index, "title": title, "imageinfo": [{"width": w, "height": h, "size": size}]}


def search_body(pages, next_offset=None):
    data = {"query": {"pages": pages}}
    if next_offset is not None:
        data["continue"] = {"gsroffset": next_offset, "continue": "-||"}
    return json.dumps(data)


def test_search_url_asks_for_big_bitmaps():
    q = query_of(commons.search_url(5120, 1440, "", 500))
    assert q["gsrsearch"] == "panorama filetype:bitmap filew:>5119 fileh:>1439"
    assert q["gsroffset"] == "500" and q["gsrlimit"] == "500" and q["iiprop"] == "size"
    assert query_of(commons.search_url(5120, 1440, " alps "))["gsrsearch"].startswith("alps ")


def test_only_desktop_shaped_images_are_kept_in_rank_order():
    body = search_body(
        [
            page(3, "File:C.jpg", 10240, 2880),  # exactly 32:9
            page(1, "File:A.jpg", 7000, 1980),  # 0.6% off: fits
            page(2, "File:Wide.jpg", 9000, 1500),  # 48:9-ish: would be cropped
            page(4, "File:Small.jpg", 4000, 1125),  # too small
            page(5, "File:Huge.jpg", 64561, 18160, size=400_000_000),
            {"index": 6, "title": "File:Gone.jpg"},  # no imageinfo
        ],
        next_offset=500,
    )
    found, nxt = commons.parse_search(body, 5120, 1440)
    assert [c.title for c in found] == ["File:A.jpg", "File:C.jpg"]
    assert nxt == 500
    found, _ = commons.parse_search(body, 5120, 1440, match_shape=False)
    assert "File:Wide.jpg" in [c.title for c in found]


def test_last_page_has_no_next_offset():
    assert commons.parse_search(search_body([]), 5120, 1440) == ([], None)


def test_api_errors_raise():
    with pytest.raises(ValueError, match="bad"):
        commons.parse_search(json.dumps({"error": {"info": "bad"}}), 5120, 1440)


DETAILS = {
    "query": {
        "pages": [
            {
                "pageid": 7,
                "title": "File:B.JPG",
                "imageinfo": [
                    {
                        "width": 10240,
                        "height": 2880,
                        "url": "https://upload.wikimedia.org/x/B.JPG?utm_source=commons.wikimedia.org&utm_content=original",
                        "descriptionurl": "https://commons.wikimedia.org/wiki/File:B.JPG",
                        "thumburl": "https://upload.wikimedia.org/thumb/960px-B.JPG",
                        "extmetadata": {
                            "Artist": {"value": '<a href="//x">Jane &amp; Co</a>'},
                            "LicenseShortName": {"value": "CC BY-SA 4.0"},
                        },
                    }
                ],
            },
            {"pageid": 8, "title": "File:A.jpg", "missing": True},
        ]
    }
}


def test_details_become_wallpapers_with_credit():
    cands = [Candidate("File:A.jpg", 1, 1), Candidate("File:B.JPG", 10240, 2880)]
    [wp] = commons.parse_details(json.dumps(DETAILS), cands)
    assert wp.id == "commons:7" and wp.filename == "commons-7.jpg"
    assert wp.credit == "Jane & Co · CC BY-SA 4.0"
    assert wp.thumb_url.endswith("960px-B.JPG")
    assert query_of(commons.details_url(cands))["titles"] == "File:A.jpg|File:B.JPG"


def test_find_pages_until_enough_then_fetches_details(monkeypatch):
    urls = []

    def fake_fetch(url, timeout=30):
        urls.append(url)
        q = query_of(url)
        if "titles" in q:
            return json.dumps(DETAILS).encode()
        offset = int(q.get("gsroffset", 0))
        hit = page(1, "File:B.JPG", 10240, 2880) if offset == 1000 else page(1, "File:N.jpg", 10, 10)
        return search_body([hit], next_offset=offset + 500).encode()

    monkeypatch.setattr(wallhaven, "_fetch", fake_fetch)
    monkeypatch.setattr(commons, "MAX_PAGES", 4)
    found = commons.find(5120, 1440, 1, SearchFilters(source="commons"))
    assert [w.id for w in found] == ["commons:7"]
    assert len(urls) == 5  # 4 search pages (only one hit, wanted 2) + 1 details


def test_import_uses_the_chosen_source(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(commons, "find", lambda *a: calls.append("commons") or [])
    monkeypatch.setattr(wallhaven, "find_random", lambda *a: calls.append("wallhaven") or [])
    wallhaven.import_random(5120, 1440, 3, tmp_path, filters=SearchFilters(source="commons"))
    wallhaven.import_random(5120, 1440, 3, tmp_path, filters=SearchFilters())
    assert calls == ["commons", "wallhaven"]


def test_cli_source_flag():
    args = build_parser().parse_args(["fetch", "3", "--source", "commons", "--search", "alps"])
    assert _filters_from(args) == SearchFilters(query="alps", source="commons")


def test_filter_bar_switches_off_wallhaven_only_filters(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from wallstitch.filter_bar import FilterBar

    bar = FilterBar((5120, 1440))
    bar.source.setCurrentIndex(bar.source.findData("commons"))
    assert bar.filters().source == "commons"
    assert not bar.color.isEnabled() and not bar.category.isEnabled() and not bar.sort.isEnabled()
    bar.set_filters(SearchFilters())
    assert bar.color.isEnabled() and bar.filters().source == "wallhaven"
