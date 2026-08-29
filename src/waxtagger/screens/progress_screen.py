"""
Screen 3: Progress window shown during batch enrichment.
"""

from typing import TYPE_CHECKING, Callable, Optional

import toga
from toga.style import Pack
from toga.style.pack import COLUMN, ROW

if TYPE_CHECKING:
    from waxtagger.app import WaxTaggerApp


class ProgressScreen:
    def __init__(self, app: "WaxTaggerApp", total: int):
        self.app = app
        self.total = total
        self._window: toga.Window = None
        self._cancel_callback: Optional[Callable] = None

        # Widgets
        self._track_label: toga.Label = None
        self._progress_bar: toga.ProgressBar = None
        self._log_area: toga.MultilineTextInput = None
        self._cancel_btn: toga.Button = None

    def build_window(self) -> toga.Window:
        style_col = Pack(direction=COLUMN, margin=12, flex=1)

        self._track_label = toga.Label(
            "Preparing…",
            style=Pack(margin=(0, 0, 4, 0)),
        )
        self._progress_bar = toga.ProgressBar(
            max=self.total,
            value=0,
            style=Pack(margin=(0, 0, 8, 0)),
        )
        self._log_area = toga.MultilineTextInput(
            readonly=True,
            style=Pack(flex=1, margin=(0, 0, 8, 0)),
        )
        self._cancel_btn = toga.Button(
            "Cancel",
            on_press=self._on_cancel,
            style=Pack(margin=4),
        )

        content = toga.Box(
            children=[
                self._track_label,
                self._progress_bar,
                self._log_area,
                toga.Box(
                    children=[self._cancel_btn],
                    style=Pack(direction=ROW, align_items="end"),
                ),
            ],
            style=style_col,
        )

        self._window = toga.Window(title="WaxTagger — Processing", size=(600, 400))
        self._window.content = content
        return self._window

    def set_cancel_callback(self, callback: Callable):
        self._cancel_callback = callback

    def update(self, msg: str, idx: int, total: int):
        """Called from main thread (via call_soon_threadsafe) to update UI."""
        if self._track_label:
            self._track_label.text = f"Track {idx}/{total}: {msg}"
        if self._progress_bar:
            self._progress_bar.value = idx
        if self._log_area and msg:
            current = self._log_area.value or ""
            self._log_area.value = current + msg + "\n"

    def _on_cancel(self, widget):
        if self._cancel_callback:
            self._cancel_callback()
        if self._cancel_btn:
            self._cancel_btn.enabled = False
            self._cancel_btn.text = "Cancelling…"
