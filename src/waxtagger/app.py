"""
WaxTagger — main Toga application.
"""

import os
import sys

import toga
from toga.style import Pack
from toga.style.pack import COLUMN

from waxtagger.enricher import ClientRegistry, TrackResult, FIELDS
from waxtagger.screens.main_screen import MainScreen
from waxtagger.screens.settings_screen import SettingsScreen
from waxtagger import config


class WaxTaggerApp(toga.App):
    def startup(self):
        self.registry = ClientRegistry()
        self.batch_results: list[TrackResult] = []
        self._settings_window = None

        # Main screen
        self.main_screen = MainScreen(app=self)
        content = self.main_screen.build()

        self.main_window = toga.MainWindow(
            title="WaxTagger",
            size=(520, 340),
        )
        self.main_window.content = content
        self.main_window.show()

        # Toolbar: Settings command
        settings_cmd = toga.Command(
            self._open_settings,
            text="Settings",
            tooltip="Manage API credentials",
            shortcut=toga.Key.MOD_1 + ",",
            icon=None,
        )
        self.commands.add(settings_cmd)
        self.main_window.toolbar.add(settings_cmd)

        # Load playlists once the event loop is running
        self.on_running = self._on_running

    async def _on_running(self, app):
        await self.main_screen.load_playlists()
        if not (config.has_discogs_credentials() or config.has_spotify_credentials()):
            # First run without any credentials: open Settings with an explanation.
            await self._open_settings(None, first_run=True)

    async def _open_settings(self, widget, first_run: bool = False):
        if self._settings_window is None or not self._settings_window.app:
            settings_screen = SettingsScreen(app=self, first_run=first_run)
            self._settings_window = settings_screen.build_window()
        self._settings_window.show()

    def exit(self) -> None:
        """
        Hard exit. The Briefcase stub drains an autorelease pool after
        Py_Finalize, which calls back into the finalized interpreter via
        rubicon/ctypes and segfaults ("WaxTagger quit unexpectedly").
        Everything WaxTagger writes is flushed synchronously before this point,
        so ending the process here is safe.
        """
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        finally:
            os._exit(0)


def main():
    app = WaxTaggerApp(
        formal_name="WaxTagger",
        app_id="com.gijspouwels.waxtagger",
    )
    app.main_loop()
