# SPDX-FileCopyrightText: 2026 Travis Estill <immyouany@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Dialog to search wallhaven.cc for wallpapers sized for the desktop."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QImage, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QToolButton,
    QVBoxLayout,
)

from wallstitch import USER_AGENT, commons
from wallstitch.filter_bar import FilterBar
from wallstitch.paths import download_dir
from wallstitch.wallhaven import SearchFilters, Wallpaper, parse_search_page, search_url, shape_ratios

COUNT = 10
THUMB_WIDTH = 300
FILTER_DELAY_MS = 400  # wait for the user to finish clicking before searching
COMMONS_PAGES_PER_STEP = 6  # Commons pages to scan before showing what was found


class WallhavenDialog(QDialog):
    """Pick one of 10 wallpapers at a time; ``chosen_path`` is set on accept."""

    def __init__(self, min_width: int, min_height: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Find Wallpapers")
        self.min_width, self.min_height = min_width, min_height
        self.chosen_path: Path | None = None
        self._replies: list[QNetworkReply] = []

        # Search state: results so far, which 10 are shown, and paging info.
        self.filters = SearchFilters()
        self.results: list[Wallpaper] = []
        self.offset = 0
        self.page = 0
        self.last_page = 1
        self.seed: str | None = None
        self.ratios: list[str | None] = []  # shape filters still to try
        # Commons: fitting files whose links aren't fetched yet, and where to search next.
        self.pending: list[commons.Candidate] = []
        self.commons_offset: int | None = 0
        self.scanned = 0

        self.net = QNetworkAccessManager(self)

        self.filter_bar = FilterBar((min_width, min_height))
        self.filter_bar.searchRequested.connect(self.new_search)
        self._refilter = QTimer(self, singleShot=True, interval=FILTER_DELAY_MS)
        self._refilter.timeout.connect(self.new_search)
        # Typing only searches on Enter; clicking a filter searches by itself.
        for signal in (
            self.filter_bar.source.currentIndexChanged,
            self.filter_bar.category.currentIndexChanged,
            self.filter_bar.sort.currentIndexChanged,
            self.filter_bar.color.currentIndexChanged,
            self.filter_bar.match_shape.toggled,
        ):
            signal.connect(self._refilter.start)

        aspect = min_width / min_height
        self.icon_size = QSize(THUMB_WIDTH, max(80, round(THUMB_WIDTH / aspect)))
        columns = 2 if aspect >= 2 else 5

        self.buttons: list[QToolButton] = []
        grid = QGridLayout()
        for i in range(COUNT):
            btn = QToolButton()
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            btn.setIconSize(self.icon_size)
            btn.setAutoRaise(True)
            btn.setVisible(False)
            btn.clicked.connect(lambda _=False, i=i: self.choose(i))
            btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            btn.customContextMenuRequested.connect(
                lambda _pos, i=i: QDesktopServices.openUrl(QUrl(self.wallpapers[i].page_url))
            )
            grid.addWidget(btn, i // columns, i % columns)
            self.buttons.append(btn)
        self.wallpapers: list[Wallpaper] = []  # the ones on screen

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.progress = QProgressBar()
        self.progress.setVisible(False)

        self.more_btn = QPushButton()
        self.more_btn.clicked.connect(self.more)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)

        bar = QHBoxLayout()
        bar.addWidget(self.status, 1)
        bar.addWidget(self.more_btn)
        bar.addWidget(cancel)

        layout = QVBoxLayout(self)
        layout.addWidget(self.filter_bar)
        layout.addLayout(grid, 1)
        layout.addWidget(self.progress)
        layout.addLayout(bar)

        self.new_search()

    # --- networking --------------------------------------------------------

    def _get(self, url: str) -> QNetworkReply:
        request = QNetworkRequest(QUrl(url))
        request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, USER_AGENT)
        reply = self.net.get(request)
        self._replies.append(reply)
        reply.finished.connect(lambda: self._replies.remove(reply) if reply in self._replies else None)
        return reply

    def _abort_all(self) -> None:
        for reply in list(self._replies):
            reply.abort()

    # --- searching ---------------------------------------------------------

    def new_search(self) -> None:
        self._refilter.stop()
        self._abort_all()
        self.filters = self.filter_bar.filters()
        self.filters.save()
        self.results, self.offset = [], 0
        self.ratios = shape_ratios(self.min_width, self.min_height, self.filters)
        self.pending, self.commons_offset = [], 0
        shuffle = self.filters.is_random and not self.is_commons
        self.more_btn.setText("Shuffle" if shuffle else "More")
        self.more_btn.setToolTip("Show 10 different wallpapers" if shuffle else "Show the next 10 results")
        self._start_ratio()

    @property
    def is_commons(self) -> bool:
        return self.filters.source == "commons"

    @property
    def source_name(self) -> str:
        return "Wikimedia Commons" if self.is_commons else "wallhaven"

    def _start_ratio(self) -> None:
        self.page, self.last_page, self.seed = 0, 1, None
        self._fetch_page()

    def _has_more(self) -> bool:
        if self.is_commons:
            return bool(self.pending) or self.commons_offset is not None
        return self.page < self.last_page

    def _fetch_page(self) -> None:
        for btn in self.buttons:
            btn.setVisible(False)
        self.more_btn.setEnabled(False)
        self.status.setText("Searching…")
        if self.is_commons:
            self.scanned = 0
            self._commons_step()
            return
        self.page += 1
        url = search_url(self.min_width, self.min_height, self.ratios[0], self.page, self.seed, self.filters)
        reply = self._get(url)
        reply.finished.connect(lambda: self._on_search(reply))

    def _body(self, reply: QNetworkReply) -> bytes | None:
        """The reply's data, or None after showing what went wrong."""
        self.more_btn.setEnabled(True)
        if reply.error() == QNetworkReply.NetworkError.OperationCanceledError:
            return None
        if reply.error() != QNetworkReply.NetworkError.NoError:
            self.status.setText(f"Couldn't reach {self.source_name}: {reply.errorString()}")
            return None
        return bytes(reply.readAll())

    # Commons can't filter by shape, so scan pages of results until enough fit,
    # then fetch links and thumbnails for those in one go.

    def _commons_step(self) -> None:
        enough = len(self.pending) >= COUNT or self.scanned >= COMMONS_PAGES_PER_STEP
        if self.pending and (enough or self.commons_offset is None):
            batch = self.pending[: commons.DETAILS_BATCH]
            self.pending = self.pending[commons.DETAILS_BATCH :]
            reply = self._get(commons.details_url(batch))
            reply.finished.connect(lambda: self._on_commons_details(reply, batch))
        elif self.commons_offset is not None and self.scanned < COMMONS_PAGES_PER_STEP:
            self.more_btn.setEnabled(False)
            self.status.setText(f"Searching… checked {self.commons_offset} images")
            url = commons.search_url(self.min_width, self.min_height, self.filters.query, self.commons_offset)
            reply = self._get(url)
            reply.finished.connect(lambda: self._on_commons_search(reply))
        else:
            self._show()

    def _on_commons_search(self, reply: QNetworkReply) -> None:
        body = self._body(reply)
        if body is None:
            return
        try:
            found, self.commons_offset = commons.parse_search(
                body, self.min_width, self.min_height, self.filters.match_shape
            )
        except ValueError as e:
            self.status.setText(f"Wikimedia Commons error: {e}")
            return
        known = {c.title for c in self.pending} | {w.page_url for w in self.results}
        self.pending += [c for c in found if c.title not in known]
        self.scanned += 1
        self._commons_step()

    def _on_commons_details(self, reply: QNetworkReply, batch: list[commons.Candidate]) -> None:
        body = self._body(reply)
        if body is None:
            return
        try:
            self.results += commons.parse_details(body, batch)
        except ValueError as e:
            self.status.setText(f"Wikimedia Commons error: {e}")
            return
        self._show()

    def _on_search(self, reply: QNetworkReply) -> None:
        body = self._body(reply)
        if body is None:
            return
        try:
            found, meta = parse_search_page(body)
        except ValueError as e:
            self.status.setText(f"Wallhaven error: {e}")
            return
        self.seed = meta.get("seed") or self.seed
        self.last_page = int(meta.get("last_page") or 1)

        if not found and not self.results and len(self.ratios) > 1:
            # Nothing in the desktop's exact shape: widen to any shape.
            self.ratios.pop(0)
            self._start_ratio()
            return
        known = {w.id for w in self.results}
        self.results += [w for w in found if w.id not in known]
        self._show()

    def _show(self) -> None:
        self.wallpapers = self.results[self.offset : self.offset + COUNT]
        if not self.wallpapers and self.is_commons and self._has_more():
            self.status.setText(
                f"None of the first {self.commons_offset} images fit yet. "
                "Press More to keep looking, or try other words."
            )
            return
        if not self.wallpapers:
            self.status.setText(
                "No wallpapers match these filters. Try fewer words, another color, "
                "or untick “Match my screen shape”."
            )
            return
        for btn in self.buttons:
            btn.setVisible(False)
        for btn, wp in zip(self.buttons, self.wallpapers, strict=False):
            btn.setIcon(QPixmap())
            btn.setText(f"{wp.width}×{wp.height}")
            credit = f"{wp.credit}\n" if wp.credit else ""
            btn.setToolTip(f"{wp.page_url}\n{credit}Click to use · right-click to open its page")
            btn.setVisible(True)
            thumb = self._get(wp.thumb_url)
            thumb.finished.connect(lambda thumb=thumb, btn=btn: self._on_thumb(thumb, btn))

        shown = f"{self.offset + 1}–{self.offset + len(self.wallpapers)}"
        message = f"Showing {shown}. Click a wallpaper to use it."
        exact_only = self.filters.match_shape and self.ratios[0] is not None
        if self.is_commons:
            message += " Freely licensed; hover for the author and license."
        elif exact_only and self.page >= self.last_page and len(self.results) < 2 * COUNT:
            message += f" Only {len(self.results)} match your screen shape — untick it for more."
        elif self.filters.match_shape and self.ratios[0] is None:
            message += " Nothing matched your screen shape, so these are other shapes."
        self.status.setText(message)

    def more(self) -> None:
        self._abort_all()
        # Step past what's on screen; if nothing was found yet, keep looking from here.
        self.offset = min(self.offset + len(self.wallpapers), len(self.results))
        if self.offset + COUNT > len(self.results) and self._has_more():
            self._fetch_page()
        elif self.offset < len(self.results):
            self._show()
        elif self.filters.is_random and not self.is_commons:
            self.new_search()  # seen them all: start a fresh random order
        else:
            self.offset = 0  # end of the results: wrap around
            self._show()

    def _on_thumb(self, reply: QNetworkReply, btn: QToolButton) -> None:
        if reply.error() != QNetworkReply.NetworkError.NoError:
            return
        image = QImage.fromData(bytes(reply.readAll()))
        if image.isNull():
            return
        scaled = image.scaled(
            self.icon_size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        )
        btn.setIcon(QPixmap.fromImage(scaled))

    # --- choosing ----------------------------------------------------------

    def choose(self, index: int) -> None:
        wp = self.wallpapers[index]
        target = download_dir() / wp.filename
        if target.is_file():
            self.chosen_path = target
            self.accept()
            return

        self._abort_all()
        for btn in self.buttons:
            btn.setEnabled(False)
        self.more_btn.setEnabled(False)
        self.filter_bar.setEnabled(False)
        self.status.setText(f"Downloading {wp.width}×{wp.height} wallpaper…")
        self.progress.setValue(0)
        self.progress.setVisible(True)

        reply = self._get(wp.image_url)
        reply.downloadProgress.connect(self._on_progress)
        reply.finished.connect(lambda: self._on_download(reply, target))

    def _on_progress(self, received: int, total: int) -> None:
        if total > 0:
            self.progress.setValue(round(received * 100 / total))

    def _on_download(self, reply: QNetworkReply, target: Path) -> None:
        self.progress.setVisible(False)
        for btn in self.buttons:
            btn.setEnabled(True)
        self.more_btn.setEnabled(True)
        self.filter_bar.setEnabled(True)
        if reply.error() == QNetworkReply.NetworkError.OperationCanceledError:
            return
        if reply.error() != QNetworkReply.NetworkError.NoError:
            self.status.setText(f"Download failed: {reply.errorString()}")
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix(target.suffix + ".part")
        partial.write_bytes(bytes(reply.readAll()))
        partial.replace(target)
        self.chosen_path = target
        self.accept()

    def reject(self) -> None:
        self._refilter.stop()
        self._abort_all()
        super().reject()
