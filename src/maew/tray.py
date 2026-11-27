"""Windows system tray icon with a crisp 8-bit pixel cat head rendered via Pillow."""

from __future__ import annotations

import threading
from typing import Callable

import pystray
from PIL import Image, ImageDraw

_CAT_ICON_GRID = [
    ".O....O.",
    ".OH..HO.",
    "OOHHHHOO",
    "OOOOOOOO",
    "OOOOOEOO",
    "OOOOOEMM",
    ".OOKOMMN",
    "..OOOOOO",
]

_SKIN_PALETTES = {
    "orange": {"O": "#f2993f", "H": "#f9bd74", "E": "#1a1423", "M": "#fde7c6", "N": "#f4729b", "K": "#f89eb6"},
    "greige": {"O": "#b29c84", "H": "#cfc0ad", "E": "#1c1614", "M": "#f2eadf", "N": "#f2789b", "K": "#f59eb6"},
    "black_yellow": {"O": "#343746", "H": "#4b4f64", "E": "#facc15", "M": "#424658", "N": "#f2789b", "K": "#f28aa8"},
    "white": {"O": "#f1f3f8", "H": "#ffffff", "E": "#1e2438", "M": "#ffffff", "N": "#f4729b", "K": "#f9a4bc"},
    "choco": {"O": "#8a5233", "H": "#a66c49", "E": "#1a1210", "M": "#c79a76", "N": "#f4729b", "K": "#f498b2"},
}


def make_cat_tray_image(skin: str = "orange", size: int = 32) -> Image.Image:
    palette = _SKIN_PALETTES.get(skin, _SKIN_PALETTES["orange"])
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    cell = max(1, size // 8)
    for y, row in enumerate(_CAT_ICON_GRID):
        for x, ch in enumerate(row):
            color = palette.get(ch)
            if not color:
                continue
            draw.rectangle(
                [x * cell, y * cell, (x + 1) * cell - 1, (y + 1) * cell - 1],
                fill=color,
            )
    return img


class MaewTray:
    def __init__(
        self,
        *,
        skin: str,
        on_toggle: Callable[[], None],
        on_refresh: Callable[[], None],
        on_compact: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        self._on_toggle = on_toggle
        self._on_refresh = on_refresh
        self._on_compact = on_compact
        self._on_quit = on_quit
        self._icon = pystray.Icon(
            "maew-usage",
            make_cat_tray_image(skin),
            "maew usage",
            menu=pystray.Menu(
                pystray.MenuItem("Show / Hide", self._toggle, default=True),
                pystray.MenuItem("Refresh Now", self._refresh),
                pystray.MenuItem("Compact Mode", self._compact),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit", self._quit),
            ),
        )
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._icon.run, name="maew-tray", daemon=True)
        self._thread.start()

    def update(self, *, skin: str | None = None, tooltip: str | None = None) -> None:
        try:
            if skin is not None:
                self._icon.icon = make_cat_tray_image(skin)
            if tooltip is not None:
                # Windows tray tooltip limit is 127 chars.
                self._icon.title = tooltip[:120]
        except Exception:  # noqa: BLE001
            pass

    def stop(self) -> None:
        try:
            self._icon.stop()
        except Exception:  # noqa: BLE001
            pass

    def _toggle(self, _icon, _item) -> None:
        self._on_toggle()

    def _refresh(self, _icon, _item) -> None:
        self._on_refresh()

    def _compact(self, _icon, _item) -> None:
        self._on_compact()

    def _quit(self, _icon, _item) -> None:
        self._on_quit()
