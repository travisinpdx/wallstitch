# SPDX-FileCopyrightText: 2026 Travis Estill <immyouany@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

import json
from urllib.parse import parse_qs, urlparse

import pytest

from wallstitch import wallhaven
from wallstitch.cli import _filters_from, build_parser
from wallstitch.wallhaven import SORTS, SearchFilters, search_url, shape_ratios


def query_of(url):
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


def test_defaults_match_the_old_random_search():
    q = query_of(search_url(5120, 1440, "32x9"))
    assert q["sorting"] == "random"
    assert q["categories"] == "111"
    assert q["purity"] == "100"
    assert "q" not in q and "colors" not in q


def test_filters_become_query_parameters():
    f = SearchFilters(
        query=" +space -planet ", anime=False, people=False, sort="Top this year", color="336600"
    )
    q = query_of(search_url(5120, 1440, "32x9", filters=f))
    assert q["q"] == "+space -planet"
    assert q["categories"] == "100"
    assert q["sorting"] == "toplist" and q["topRange"] == "1y"
    assert q["colors"] == "336600"
    assert q["purity"] == "100"  # SFW can't be switched off by filters


def test_no_categories_ticked_means_all():
    assert SearchFilters(general=False, anime=False, people=False).categories == "111"


def test_unknown_sort_and_color_are_ignored():
    q = SearchFilters(sort="Bogus", color="123456").params()
    assert q["sorting"] == "random" and "colors" not in q


def test_every_sort_label_maps_to_a_wallhaven_sort():
    valid = {"random", "relevance", "favorites", "toplist", "views", "date_added", "hot"}
    assert {sorting for sorting, _ in SORTS.values()} <= valid


def test_shape_ratios():
    assert shape_ratios(5120, 1440, SearchFilters()) == ["32x9", None]
    assert shape_ratios(5120, 1440, SearchFilters(match_shape=False)) == [None]
    assert shape_ratios(2560, 2880, SearchFilters()) == [None]  # no common ratio this shape


def test_filters_round_trip_and_ignore_unknown_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert SearchFilters.load() == SearchFilters()
    f = SearchFilters(query="forest", people=False, sort="Newest", color="669900", match_shape=False)
    f.save()
    assert SearchFilters.load() == f
    path = tmp_path / "wallstitch" / "search.json"
    path.write_text(json.dumps({**json.loads(path.read_text()), "from_the_future": 1}))
    assert SearchFilters.load() == f


def test_find_random_any_shape_skips_ratio(monkeypatch):
    urls = []

    def fake_fetch(url, timeout=30):
        urls.append(url)
        return json.dumps({"data": [], "meta": {"last_page": 1}}).encode()

    monkeypatch.setattr(wallhaven, "_fetch", fake_fetch)
    wallhaven.find_random(5120, 1440, 5, SearchFilters(query="x", match_shape=False))
    assert len(urls) == 1 and "ratios" not in urls[0] and "q=x" in urls[0]


@pytest.mark.parametrize("command", [["fetch", "5"], ["slideshow", "start", "--fetch", "5"]])
def test_cli_search_flags(command):
    args = build_parser().parse_args(
        [
            *command,
            "--search",
            "neon city",
            "--category",
            "general",
            "--category",
            "anime",
            "--sort",
            "newest",
            "--color",
            "#0066CC",
            "--any-shape",
        ]
    )
    f = _filters_from(args)
    assert f == SearchFilters(
        query="neon city", people=False, sort="Newest", color="0066cc", match_shape=False
    )


def test_cli_defaults_ignore_saved_gui_filters(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    SearchFilters(query="saved in the gui").save()
    assert _filters_from(build_parser().parse_args(["fetch", "3"])) == SearchFilters()


@pytest.fixture
def qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_category_dropdown_round_trips_every_choice(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from wallstitch.filter_bar import CATEGORY_CHOICES, FilterBar

    bar = FilterBar((5120, 1440))
    for label, bits in CATEGORY_CHOICES.items():
        bar.category.setCurrentText(label)
        f = bar.filters()
        assert f.categories == bits
        bar.set_filters(SearchFilters())
        bar.set_filters(f)
        assert bar.category.currentText() == label


def test_category_dropdown_reports_changes(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from wallstitch.filter_bar import FilterBar

    bar = FilterBar((5120, 1440))
    changes = []
    bar.filtersChanged.connect(lambda: changes.append(1))
    bar.category.setCurrentText("Anime")
    assert changes and bar.filters().params()["categories"] == "010"


def test_cli_rejects_colors_wallhaven_does_not_have():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["fetch", "3", "--color", "123456"])
