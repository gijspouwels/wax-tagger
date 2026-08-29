"""
Screen 1: Library selection (Music.app playlist or folder), source/field/mode
options, Start button.
"""

import asyncio
import os
from typing import TYPE_CHECKING

import toga
from toga.style import Pack
from toga.style.pack import COLUMN, ROW

from waxtagger.enricher import FIELDS, DEFAULT_RENAME_PATTERN, run_batch
from waxtagger.itunes.bridge import get_playlists, get_tracks_from_playlist, check_music_running
from waxtagger.folder.bridge import get_tracks_from_folder, RENAME_VARIABLES

if TYPE_CHECKING:
    from waxtagger.app import WaxTaggerApp


LIBRARY_MUSIC = "Music.app playlist"
LIBRARY_FOLDER = "Folder on disk"


class MainScreen:
    def __init__(self, app: "WaxTaggerApp"):
        self.app = app
        self._playlists: list[dict] = []
        self._folder_path: str = ""

        # Widgets (set during build())
        self._library_sel: toga.Selection = None
        self._playlist_sel: toga.Selection = None
        self._playlist_row: toga.Box = None
        self._folder_row: toga.Box = None
        self._folder_label: toga.Label = None
        self._recursive_sw: toga.Switch = None
        self._rename_row: toga.Box = None
        self._rename_sw: toga.Switch = None
        self._rename_input: toga.TextInput = None
        self._source_sel: toga.Selection = None
        self._mode_sel: toga.Selection = None
        self._field_switches: dict[str, toga.Switch] = {}
        self._overwrite_sw: toga.Switch = None
        self._ignore_pinned_sw: toga.Switch = None
        self._clear_empty_sw: toga.Switch = None
        self._start_btn: toga.Button = None
        self._status_label: toga.Label = None

    def build(self) -> toga.Box:
        style_row = Pack(direction=ROW, margin=4, align_items="center")
        style_label = Pack(margin=(0, 8, 0, 0), width=110)
        style_col = Pack(direction=COLUMN, margin=8)

        # ── Library row ───────────────────────────────────────────────────────
        self._library_sel = toga.Selection(
            items=[LIBRARY_MUSIC, LIBRARY_FOLDER],
            on_change=self._on_library_change,
            style=Pack(flex=1),
        )
        library_row = toga.Box(
            children=[
                toga.Label("Library", style=style_label),
                self._library_sel,
            ],
            style=style_row,
        )

        # ── Playlist row (Music.app) ──────────────────────────────────────────
        self._playlist_sel = toga.Selection(
            items=["Loading…"],
            style=Pack(flex=1),
        )
        refresh_btn = toga.Button(
            "↺",
            on_press=self._on_refresh,
            style=Pack(margin=(0, 0, 0, 4)),
        )
        self._playlist_row = toga.Box(
            children=[
                toga.Label("Playlist", style=style_label),
                self._playlist_sel,
                refresh_btn,
            ],
            style=style_row,
        )

        # ── Folder row ────────────────────────────────────────────────────────
        self._folder_label = toga.Label("(no folder selected)", style=Pack(flex=1))
        browse_btn = toga.Button(
            "Choose…",
            on_press=self._on_browse,
            style=Pack(margin=(0, 4, 0, 0)),
        )
        self._recursive_sw = toga.Switch("Include subfolders", value=True)
        self._folder_row = toga.Box(
            children=[
                toga.Label("Folder", style=style_label),
                browse_btn,
                self._folder_label,
                self._recursive_sw,
            ],
            style=style_row,
        )

        # ── Rename row (folder mode only) ─────────────────────────────────────
        self._rename_sw = toga.Switch(
            "Rename files to",
            value=False,
            on_change=self._on_rename_toggle,
        )
        self._rename_input = toga.TextInput(
            value=DEFAULT_RENAME_PATTERN,
            placeholder=DEFAULT_RENAME_PATTERN,
            style=Pack(flex=1, margin=(0, 8)),
        )
        self._rename_input.enabled = False
        vars_hint = toga.Label(
            " ".join("{%s}" % v for v in RENAME_VARIABLES),
            style=Pack(font_size=10, color="#888888"),
        )
        self._rename_row = toga.Box(
            children=[
                toga.Label("Filenames", style=style_label),
                self._rename_sw,
                self._rename_input,
            ],
            style=style_row,
        )
        rename_hint_row = toga.Box(
            children=[toga.Label("", style=style_label), vars_hint],
            style=Pack(direction=ROW, margin=(0, 4, 4, 4)),
        )
        self._rename_hint_row = rename_hint_row

        # ── Source row ────────────────────────────────────────────────────────
        self._source_sel = toga.Selection(
            items=["Discogs", "Spotify"],
            style=Pack(flex=1),
        )
        source_row = toga.Box(
            children=[
                toga.Label("Source", style=style_label),
                self._source_sel,
            ],
            style=style_row,
        )

        # ── Fields ────────────────────────────────────────────────────────────
        fields_box = toga.Box(style=style_row)
        fields_box.add(toga.Label("Fields", style=style_label))
        for f in FIELDS:
            sw = toga.Switch(f.capitalize(), value=True)
            self._field_switches[f] = sw
            fields_box.add(sw)

        # ── Mode row ──────────────────────────────────────────────────────────
        self._mode_sel = toga.Selection(
            items=["Auto", "Dry Run"],
            style=Pack(flex=1),
        )
        mode_row = toga.Box(
            children=[
                toga.Label("Mode", style=style_label),
                self._mode_sel,
            ],
            style=style_row,
        )

        # ── Options row ───────────────────────────────────────────────────────
        self._overwrite_sw = toga.Switch("Overwrite existing", value=False)
        self._ignore_pinned_sw = toga.Switch("Ignore pinned URLs", value=False)
        self._clear_empty_sw = toga.Switch("Clear empty fields", value=False)
        options_row = toga.Box(
            children=[
                toga.Label("Options", style=style_label),
                self._overwrite_sw,
                self._ignore_pinned_sw,
                self._clear_empty_sw,
            ],
            style=style_row,
        )

        # ── Start button + status ─────────────────────────────────────────────
        self._start_btn = toga.Button(
            "Start →",
            on_press=self._on_start,
            style=Pack(margin=8),
        )
        self._status_label = toga.Label("", style=Pack(flex=1, margin=8))
        bottom_row = toga.Box(
            children=[self._status_label, self._start_btn],
            style=Pack(direction=ROW, margin=8, align_items="center"),
        )

        # ── Layout ────────────────────────────────────────────────────────────
        self._box = toga.Box(
            children=[
                library_row,
                self._playlist_row,
                source_row,
                fields_box,
                mode_row,
                options_row,
                bottom_row,
            ],
            style=style_col,
        )
        return self._box

    # ── Library switching ─────────────────────────────────────────────────────

    def _on_library_change(self, widget):
        """Swap the playlist row for the folder + rename rows, and back."""
        if not getattr(self, "_box", None):
            return  # on_change can fire while build() is still assembling widgets
        folder_mode = self._library_sel.value == LIBRARY_FOLDER
        children = list(self._box.children)

        for row in (self._playlist_row, self._folder_row, self._rename_row, self._rename_hint_row):
            if row in children:
                self._box.remove(row)

        if folder_mode:
            self._box.insert(1, self._folder_row)
            self._box.insert(2, self._rename_row)
            self._box.insert(3, self._rename_hint_row)
        else:
            self._box.insert(1, self._playlist_row)

    async def _on_browse(self, widget):
        try:
            path = await self.app.main_window.dialog(
                toga.SelectFolderDialog("Choose a folder with audio files")
            )
        except Exception as e:
            self._set_status(f"Error: {e}")
            return

        if not path:
            return

        self._folder_path = str(path)
        self._folder_label.text = self._folder_path
        self._set_status("")

    def _on_rename_toggle(self, widget):
        self._rename_input.enabled = self._rename_sw.value

    # ── Background task: load playlists ───────────────────────────────────────

    async def load_playlists(self, widget=None):
        try:
            loop = asyncio.get_event_loop()
            playlists = await loop.run_in_executor(None, get_playlists)
            self._playlists = playlists
            names = [pl["name"] for pl in playlists]
            self._playlist_sel.items = names if names else ["(no playlists found)"]
        except Exception as e:
            self._playlist_sel.items = [f"Error: {e}"]

    async def _on_refresh(self, widget):
        self._playlist_sel.items = ["Refreshing…"]
        await self.load_playlists()

    # ── Start batch ───────────────────────────────────────────────────────────

    async def _load_tracks(self, loop):
        """Load tracks from the selected library. Returns (tracks, error_message)."""
        if self._library_sel.value == LIBRARY_FOLDER:
            if not self._folder_path:
                return None, "Please choose a folder first."
            if not os.path.isdir(self._folder_path):
                return None, f"Folder not found: {self._folder_path}"
            recursive = self._recursive_sw.value
            folder = self._folder_path
            tracks = await loop.run_in_executor(
                None, lambda: get_tracks_from_folder(folder, recursive=recursive)
            )
            return tracks, None

        if not self._playlists:
            return None, "No playlists loaded yet."
        selected_name = self._playlist_sel.value
        if not selected_name or selected_name.startswith("Error") or selected_name == "Loading…":
            return None, "Please select a valid playlist."
        tracks = await loop.run_in_executor(
            None, lambda: get_tracks_from_playlist(selected_name)
        )
        return tracks, None

    async def _on_start(self, widget):
        source = "discogs" if self._source_sel.value == "Discogs" else "spotify"
        fields = {f for f, sw in self._field_switches.items() if sw.value}
        overwrite = self._overwrite_sw.value
        ignore_pinned = self._ignore_pinned_sw.value
        clear_empty = self._clear_empty_sw.value
        mode = "dry" if self._mode_sel.value == "Dry Run" else "auto"

        folder_mode = self._library_sel.value == LIBRARY_FOLDER
        rename_pattern = None
        if folder_mode and self._rename_sw.value:
            rename_pattern = self._rename_input.value.strip()
            if not rename_pattern:
                await self.app.main_window.dialog(
                    toga.InfoDialog("No pattern", "Enter a filename pattern, e.g. {artist} - {title}.")
                )
                return

        if not fields:
            await self.app.main_window.dialog(
                toga.InfoDialog("No fields", "Select at least one field to enrich.")
            )
            return

        # Load tracks
        self._set_status("Loading tracks…")
        self._start_btn.enabled = False
        loop = asyncio.get_event_loop()
        try:
            tracks, error = await self._load_tracks(loop)
        except Exception as e:
            self._set_status(f"Error: {e}")
            self._start_btn.enabled = True
            return

        if error:
            self._set_status(error)
            self._start_btn.enabled = True
            await self.app.main_window.dialog(toga.InfoDialog("Cannot start", error))
            return

        if not tracks:
            self._set_status("No tracks found.")
            self._start_btn.enabled = True
            return

        # Open progress window
        from waxtagger.screens.progress_screen import ProgressScreen
        progress_screen = ProgressScreen(app=self.app, total=len(tracks))
        progress_window = progress_screen.build_window()
        progress_window.show()

        cancelled_flag = [False]
        progress_screen.set_cancel_callback(lambda: cancelled_flag.__setitem__(0, True))

        def on_progress(msg, idx, total):
            self.app.loop.call_soon_threadsafe(
                progress_screen.update, msg, idx, total
            )

        # Run batch in thread
        try:
            results = await loop.run_in_executor(
                None,
                lambda: run_batch(
                    tracks,
                    self.app.registry,
                    source,
                    fields,
                    overwrite,
                    ignore_pinned,
                    clear_empty,
                    progress_callback=on_progress,
                    cancelled_flag=cancelled_flag,
                    rename_pattern=rename_pattern,
                )
            )
        except Exception as e:
            self._set_status(f"Batch error: {e}")
            self._start_btn.enabled = True
            progress_window.close()
            return

        self.app.batch_results = results
        progress_window.close()
        self._start_btn.enabled = True
        self._set_status(f"Done — {len(results)} tracks processed.")

        # Open review window
        from waxtagger.screens.review_screen import ReviewScreen
        review = ReviewScreen(app=self.app, results=results, mode=mode)
        review_window = review.build_window()
        review_window.show()

    def _set_status(self, msg: str):
        if self._status_label:
            self._status_label.text = msg
