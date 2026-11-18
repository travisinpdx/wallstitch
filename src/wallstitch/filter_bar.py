# SPDX-FileCopyrightText: 2026 Travis Estill <immyouany@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Search box and filters for wallhaven.cc, shared by the picker and slideshow import."""

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
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from wallstitch.wallhaven import CATEGORIES, COLORS, SORTS, SearchFilters, best_ratio


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

        self.query = QLineEdit()
        self.query.setPlaceholderText("Search wallhaven… e.g. mountains, +space -planet")
        self.query.setClearButtonEnabled(True)
        self.query.returnPressed.connect(self.searchRequested)
        self.query.textChanged.connect(self.filtersChanged)

        self.category_buttons: dict[str, QToolButton] = {}
        for name in CATEGORIES:
            btn = QToolButton()
            btn.setText(name.capitalize())
            btn.setCheckable(True)
            btn.toggled.connect(self.filtersChanged)
            self.category_buttons[name] = btn

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
        top.addWidget(self.query, 1)
        if search_button:
            go = QPushButton("Search")
            go.clicked.connect(self.searchRequested)
            top.addWidget(go)

        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        for btn in self.category_buttons.values():
            bottom.addWidget(btn)
        bottom.addSpacing(12)
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

    def filters(self) -> SearchFilters:
        return SearchFilters(
            query=self.query.text(),
            sort=self.sort.currentText(),
            color=self.color.currentData() or "",
            match_shape=self.match_shape.isChecked() and self.match_shape.isEnabled(),
            **{name: btn.isChecked() for name, btn in self.category_buttons.items()},
        )

    def set_filters(self, f: SearchFilters) -> None:
        widgets = [self.query, self.sort, self.color, self.match_shape, *self.category_buttons.values()]
        for w in widgets:
            w.blockSignals(True)
        self.query.setText(f.query)
        self.sort.setCurrentText(f.sort if f.sort in SORTS else "Random")
        self.color.setCurrentIndex(max(0, self.color.findData(f.color)))
        self.match_shape.setChecked(f.match_shape)
        for name, btn in self.category_buttons.items():
            btn.setChecked(getattr(f, name))
        for w in widgets:
            w.blockSignals(False)
