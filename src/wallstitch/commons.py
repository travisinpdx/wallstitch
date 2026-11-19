# SPDX-FileCopyrightText: 2026 Travis Estill <immyouany@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Find freely licensed panoramas on Wikimedia Commons (https://commons.wikimedia.org).

Commons can't filter by aspect ratio, so a search asks for 500 large files
at a time with just their sizes and keeps the ones shaped like the desktop.
A second request fetches download links, thumbnails and credits for those.
"""

from __future__ import annotations

import html
import json
import random
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import urlencode, urlsplit

from wallstitch import wallhaven
from wallstitch.wallhaven import SearchFilters, Wallpaper

API = "https://commons.wikimedia.org/w/api.php"
DEFAULT_QUERY = "panorama"
PAGE_SIZE = 500
DETAILS_BATCH = 50  # the API returns links and thumbnails for at most 50 files at once
MAX_PAGES = 20  # Commons stops paging at 10,000 results anyway
THUMB_WIDTH = 960
# How far an image's shape may differ from the desktop's. 2% means at most a
# sliver (about 50 px across 5120) is trimmed when it is fitted: no visible crop.
SHAPE_TOLERANCE = 0.02
MAX_BYTES = 80_000_000  # a few panoramas are 400 MB+; skip those


@dataclass(frozen=True)
class Candidate:
    """A search hit that fits; its links are fetched separately."""

    title: str
    width: int
    height: int


def fits(width: int, height: int, min_width: int, min_height: int, match_shape: bool = True) -> bool:
    if width < min_width or height < min_height:
        return False
    if not match_shape:
        return True
    return abs((width / height) / (min_width / min_height) - 1) <= SHAPE_TOLERANCE


def search_url(min_width: int, min_height: int, query: str = "", offset: int = 0) -> str:
    search = (
        f"{query.strip() or DEFAULT_QUERY} filetype:bitmap filew:>{min_width - 1} fileh:>{min_height - 1}"
    )
    params = {
        "action": "query",
        "format": "json",
        "formatversion": "2",
        "generator": "search",
        "gsrnamespace": "6",  # File: pages
        "gsrlimit": str(PAGE_SIZE),
        "gsrsearch": search,
        "prop": "imageinfo",
        "iiprop": "size",
    }
    if offset:
        params["gsroffset"] = str(offset)
    return f"{API}?{urlencode(params)}"


def _query(body: bytes | str) -> dict:
    data = json.loads(body)
    if "error" in data:
        raise ValueError(data["error"].get("info", "unexpected reply from Wikimedia Commons"))
    return data


def parse_search(
    body: bytes | str, min_width: int, min_height: int, match_shape: bool = True
) -> tuple[list[Candidate], int | None]:
    """Files that fit, best match first, plus the offset of the next page (None at the end)."""
    data = _query(body)
    pages = sorted(data.get("query", {}).get("pages", []), key=lambda p: p.get("index", 0))
    found = []
    for page in pages:
        info = (page.get("imageinfo") or [None])[0]
        if not info or info.get("size", 0) > MAX_BYTES:
            continue
        if fits(info["width"], info["height"], min_width, min_height, match_shape):
            found.append(Candidate(page["title"], info["width"], info["height"]))
    next_offset = data.get("continue", {}).get("gsroffset")
    return found, int(next_offset) if next_offset is not None else None


def details_url(candidates: list[Candidate]) -> str:
    params = {
        "action": "query",
        "format": "json",
        "formatversion": "2",
        "titles": "|".join(c.title for c in candidates[:DETAILS_BATCH]),
        "prop": "imageinfo",
        "iiprop": "url|size|extmetadata",
        "iiextmetadatafilter": "Artist|LicenseShortName",
        "iiurlwidth": str(THUMB_WIDTH),
    }
    return f"{API}?{urlencode(params)}"


def _plain(text: str) -> str:
    """Commons credits are HTML snippets; keep just the words."""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", text)).split())


def parse_details(body: bytes | str, candidates: list[Candidate]) -> list[Wallpaper]:
    """Wallpapers for ``candidates``, in the same order, skipping any that vanished."""
    by_title = {}
    for page in _query(body).get("query", {}).get("pages", []):
        info = (page.get("imageinfo") or [None])[0]
        if not info or "url" not in info:
            continue
        meta = info.get("extmetadata", {})
        artist = _plain(meta.get("Artist", {}).get("value", ""))
        license_ = _plain(meta.get("LicenseShortName", {}).get("value", ""))
        by_title[page["title"]] = Wallpaper(
            id=f"commons:{page['pageid']}",
            page_url=info["descriptionurl"],
            image_url=info["url"],
            thumb_url=info.get("thumburl") or info["url"],
            width=info["width"],
            height=info["height"],
            name=f"commons-{page['pageid']}{PurePosixPath(urlsplit(info['url']).path).suffix.lower()}",
            credit=" · ".join(part for part in (artist, license_) if part),
        )
    return [by_title[c.title] for c in candidates if c.title in by_title]


def find(
    min_width: int, min_height: int, count: int, filters: SearchFilters | None = None
) -> list[Wallpaper]:
    """Up to ``count`` fitting images, picked at random from the best matches (blocking)."""
    filters = filters or SearchFilters(source="commons")
    pool: dict[str, Candidate] = {}
    offset: int | None = 0
    for _ in range(MAX_PAGES):
        url = search_url(min_width, min_height, filters.query, offset or 0)
        found, offset = parse_search(wallhaven._fetch(url), min_width, min_height, filters.match_shape)
        for c in found:
            pool.setdefault(c.title, c)
        if offset is None or len(pool) >= 2 * count:
            break
    chosen = random.sample(list(pool.values()), min(count, len(pool)))
    wallpapers: list[Wallpaper] = []
    for i in range(0, len(chosen), DETAILS_BATCH):
        batch = chosen[i : i + DETAILS_BATCH]
        wallpapers += parse_details(wallhaven._fetch(details_url(batch)), batch)
    return wallpapers
