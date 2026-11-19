# SPDX-FileCopyrightText: 2026 Travis Estill <immyouany@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Source, search box and filters, shared by the picker and slideshow import."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from wallstitch.wallhaven import CATEGORIES, COLORS, SORTS, SOURCES, SearchFilters, best_ratio

# Category dropdown: label -> wallhaven category bits (general, anime, people)
CATEGORY_CHOICES = {
    "All categories": "111",
    "General": "100",
    "Anime": "010",
    "People": "001",
    "General + Anime": "110",
    "General + People": "101",
    "Anime + People": "011",
}


def _swatch(hex_color: str) -> QIcon:
    pixmap = QPixmap(16, 16)
    pixmap.fill(QColor(f"#{hex_color}"))
    return QIcon(pixmap)


class FilterBar(QWidget):
    """Emits ``searchRequested`` on Enter/Search, ``filtersChanged`` on any other change."""

    searchRequested = Signal()
    filtersChanged = Signal()

    def __init__(self, desktop_size: tuple[int, int], search_button: bool = True, parent=None):
        super().__init__(parent)

        self.source = QComboBox()
        for key, label in SOURCES.items():
            self.source.addItem(label, key)
        self.source.setToolTip(
            "Wallhaven: wallpapers of every kind, including art and anime.\n"
            "Wikimedia Commons: freely licensed panoramic photos."
        )
        self.source.currentIndexChanged.connect(self._source_changed)
        self.source.currentIndexChanged.connect(self.filtersChanged)

        self.query = QLineEdit()
        self.query.setClearButtonEnabled(True)
        self.query.returnPressed.connect(self.searchRequested)
        self.query.textChanged.connect(self.filtersChanged)

        self.category = QComboBox()
        for label, bits in CATEGORY_CHOICES.items():
            self.category.addItem(label, bits)
        self.category.currentIndexChanged.connect(self.filtersChanged)

        self.sort = QComboBox()
        self.sort.addItems(list(SORTS))
        self.sort.currentIndexChanged.connect(self.filtersChanged)

        self.color = QComboBox()
        self.color.addItem("Any color", "")
        for hex_color in COLORS:
            self.color.addItem(_swatch(hex_color), f"#{hex_color}", hex_color)
        self.color.currentIndexChanged.connect(self.filtersChanged)

        ratio = best_ratio(*desktop_size)
        self.match_shape = QCheckBox(
            f"Match my screen shape ({ratio.replace('x', ':')})" if ratio else "Match my screen shape"
        )
        self.match_shape.setToolTip(
            "Only show images with the same proportions as your desktop, so nothing important\n"
            "gets cropped off. Untick for many more results."
        )
        self.match_shape.setEnabled(ratio is not None)
        self.match_shape.toggled.connect(self.filtersChanged)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(self.source)
        top.addWidget(self.query, 1)
        if search_button:
            go = QPushButton("Search")
            go.clicked.connect(self.searchRequested)
            top.addWidget(go)

        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.addWidget(QLabel("Category:"))
        bottom.addWidget(self.category)
        bottom.addWidget(QLabel("Sort:"))
        bottom.addWidget(self.sort)
        bottom.addWidget(QLabel("Color:"))
        bottom.addWidget(self.color)
        bottom.addSpacing(12)
        bottom.addWidget(self.match_shape)
        bottom.addStretch()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(top)
        layout.addLayout(bottom)

        self.set_filters(SearchFilters.load())

    def _source_changed(self) -> None:
        """Commons only searches by keyword, so the wallhaven filters are switched off."""
        wallhaven = self.source.currentData() == "wallhaven"
        for w in (self.category, self.sort, self.color):
            w.setEnabled(wallhaven)
        self.query.setPlaceholderText(
            "Search wallhaven… e.g. mountains, +space -planet"
            if wallhaven
            else "Search Wikimedia Commons… e.g. mountains, city skyline (default: panorama)"
        )

    def filters(self) -> SearchFilters:
        bits = self.category.currentData() or "111"
        return SearchFilters(
            query=self.query.text(),
            sort=self.sort.currentText(),
            color=self.color.currentData() or "",
            match_shape=self.match_shape.isChecked() and self.match_shape.isEnabled(),
            source=self.source.currentData(),
            **{name: bit == "1" for name, bit in zip(CATEGORIES, bits, strict=True)},
        )

    def set_filters(self, f: SearchFilters) -> None:
        widgets = [self.source, self.query, self.category, self.sort, self.color, self.match_shape]
        for w in widgets:
            w.blockSignals(True)
        self.source.setCurrentIndex(max(0, self.source.findData(f.source)))
        self.query.setText(f.query)
        self.category.setCurrentIndex(max(0, self.category.findData(f.categories)))
        self.sort.setCurrentText(f.sort if f.sort in SORTS else "Random")
        self.color.setCurrentIndex(max(0, self.color.findData(f.color)))
        self.match_shape.setChecked(f.match_shape)
        for w in widgets:
            w.blockSignals(False)
        self._source_changed()
