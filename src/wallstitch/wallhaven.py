# SPDX-FileCopyrightText: 2026 Travis Estill <immyouany@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Find wallpapers that fit the desktop on wallhaven.cc (https://wallhaven.cc/help/api).

The single-pick dialog does its networking with Qt; bulk imports use the
blocking helpers at the bottom (run them off the GUI thread).
"""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from urllib.parse import urlencode

from wallstitch import USER_AGENT, paths

SEARCH_API = "https://wallhaven.cc/api/v1/search"

# Aspect ratios wallhaven users tag images with, widest multi-monitor ones included.
RATIOS = {
    "4x3": 4 / 3,
    "16x10": 16 / 10,
    "16x9": 16 / 9,
    "21x9": 21 / 9,
    "32x9": 32 / 9,
    "48x9": 48 / 9,
    "9x16": 9 / 16,
    "10x16": 10 / 16,
}
RATIO_TOLERANCE = 0.08  # beyond this, cropping would lose too much of the image

# label -> (wallhaven "sorting", extra params). Order is the order shown in the UI.
SORTS: dict[str, tuple[str, dict[str, str]]] = {
    "Random": ("random", {}),
    "Relevance": ("relevance", {}),
    "Most favorited": ("favorites", {}),
    "Top this year": ("toplist", {"topRange": "1y"}),
    "Most viewed": ("views", {}),
    "Newest": ("date_added", {}),
    "Hot": ("hot", {}),
}

# The colour palette wallhaven.cc lets you search by (hex, no #).
COLORS = (
    "660000 990000 cc0000 cc3333 ea4c88 993399 663399 333399 0066cc 0099cc "
    "66cccc 77cc33 669900 336600 666600 999900 cccc33 ffff00 ffcc33 ff9900 "
    "ff6600 cc6633 996633 663300 000000 999999 cccccc ffffff 424153"
).split()

CATEGORIES = ("general", "anime", "people")

# Where wallpapers can come from: key -> label. See commons.py for the second one.
SOURCES = {"wallhaven": "Wallhaven", "commons": "Wikimedia Commons"}


@dataclass
class SearchFilters:
    """What to look for. Saved between sessions and shared by every search."""

    query: str = ""  # wallhaven syntax works too: "+space -planet", "id:123"
    general: bool = True
    anime: bool = True
    people: bool = True
    sort: str = "Random"  # a key of SORTS
    color: str = ""  # one of COLORS, or "" for any
    match_shape: bool = True  # only images with the desktop's aspect ratio
    source: str = "wallhaven"  # a key of SOURCES; Commons only uses query and match_shape

    @property
    def categories(self) -> str:
        bits = "".join("1" if getattr(self, c) else "0" for c in CATEGORIES)
        return bits if "1" in bits else "111"  # none ticked means "don't filter"

    @property
    def is_random(self) -> bool:
        return SORTS.get(self.sort, SORTS["Random"])[0] == "random"

    def params(self) -> dict[str, str]:
        sorting, extra = SORTS.get(self.sort, SORTS["Random"])
        out = {"sorting": sorting, "categories": self.categories, **extra}
        if self.query.strip():
            out["q"] = self.query.strip()
        if self.color in COLORS:
            out["colors"] = self.color
        return out

    @staticmethod
    def _path() -> Path:
        return paths.config_dir() / "search.json"

    def save(self) -> None:
        self._path().parent.mkdir(parents=True, exist_ok=True)
        self._path().write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def load(cls) -> SearchFilters:
        try:
            data = json.loads(cls._path().read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return cls()
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass(frozen=True)
class Wallpaper:
    id: str
    page_url: str
    image_url: str
    thumb_url: str
    width: int
    height: int
    name: str = ""  # file name to save as; defaults to the last part of image_url
    credit: str = ""  # author and license, where the source requires attribution

    @property
    def filename(self) -> str:
        return self.name or self.image_url.rsplit("/", 1)[-1]


def best_ratio(width: float, height: float) -> str | None:
    """The wallhaven ratio tag closest to ``width/height``, if one is close enough."""
    target = width / height
    name, value = min(RATIOS.items(), key=lambda kv: abs(kv[1] - target))
    return name if abs(value - target) / target <= RATIO_TOLERANCE else None


def search_url(
    min_width: int,
    min_height: int,
    ratio: str | None = None,
    page: int = 1,
    seed: str | None = None,
    filters: SearchFilters | None = None,
) -> str:
    """URL for a page of safe-for-work wallpapers at least this large.

    Pass the ``seed`` from the first page's reply to get further pages of the
    same random order without repeats.
    """
    params = {
        **(filters or SearchFilters()).params(),
        "purity": "100",  # SFW only; NSFW requires an API key anyway
        "atleast": f"{min_width}x{min_height}",
    }
    if ratio:
        params["ratios"] = ratio
    if page > 1:
        params["page"] = str(page)
    if seed:
        params["seed"] = seed
    return f"{SEARCH_API}?{urlencode(params)}"


def parse_search(body: bytes | str) -> list[Wallpaper]:
    return parse_search_page(body)[0]


def parse_search_page(body: bytes | str) -> tuple[list[Wallpaper], dict]:
    """Wallpapers plus the ``meta`` block (seed, last_page, ...)."""
    data = json.loads(body)
    if "data" not in data:
        raise ValueError(data.get("error", "unexpected reply from wallhaven"))
    results = []
    for item in data["data"]:
        w, h = (int(v) for v in item["resolution"].split("x"))
        results.append(
            Wallpaper(
                id=item["id"],
                page_url=item["url"],
                image_url=item["path"],
                # "original" keeps the aspect ratio; the others are cropped to 3:2
                thumb_url=item["thumbs"]["original"],
                width=w,
                height=h,
            )
        )
    return results, data.get("meta") or {}


# --- blocking helpers for bulk import -----------------------------------------


def _fetch(url: str, timeout: float = 30) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def shape_ratios(min_width: int, min_height: int, filters: SearchFilters) -> list[str | None]:
    """Ratio filters to try in order: the desktop's shape first, then any shape."""
    if not filters.match_shape:
        return [None]
    return list(dict.fromkeys([best_ratio(min_width, min_height), None]))


def find_random(
    min_width: int, min_height: int, count: int, filters: SearchFilters | None = None
) -> list[Wallpaper]:
    """Up to ``count`` distinct wallpapers that fit the desktop and the filters."""
    filters = filters or SearchFilters()
    for ratio in shape_ratios(min_width, min_height, filters):
        found: dict[str, Wallpaper] = {}
        seed, page, last_page = None, 1, 1
        while len(found) < count and page <= last_page:
            url = search_url(min_width, min_height, ratio, page, seed, filters)
            results, meta = parse_search_page(_fetch(url))
            seed = meta.get("seed") or seed
            last_page = int(meta.get("last_page") or 1)
            for wp in results:
                found.setdefault(wp.id, wp)
            page += 1
        if found:
            return list(found.values())[:count]
    return []


def download(wallpaper: Wallpaper, dest_dir: Path) -> Path:
    """Save the full image into ``dest_dir`` (skipped if already there)."""
    target = dest_dir / wallpaper.filename
    if target.is_file():
        return target
    dest_dir.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    partial.write_bytes(_fetch(wallpaper.image_url, timeout=120))
    partial.replace(target)
    return target


def import_random(
    min_width: int,
    min_height: int,
    count: int,
    dest_dir: Path,
    progress: Callable[[int, int], None] | None = None,
    filters: SearchFilters | None = None,
) -> list[Path]:
    """Find and download ``count`` wallpapers; returns the saved files.

    Individual failed downloads are skipped rather than aborting the batch.
    """
    if filters and filters.source == "commons":
        from wallstitch import commons

        wallpapers = commons.find(min_width, min_height, count, filters)
    else:
        wallpapers = find_random(min_width, min_height, count, filters)
    paths: list[Path] = []
    for i, wp in enumerate(wallpapers):
        if progress:
            progress(i, len(wallpapers))
        try:
            paths.append(download(wp, dest_dir))
        except OSError:
            continue
    if progress:
        progress(len(wallpapers), len(wallpapers))
    return paths
