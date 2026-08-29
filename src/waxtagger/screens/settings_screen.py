"""
Settings screen: API credentials for Discogs and Spotify.

Values are stored in the user config file (~/Library/Application Support/
WaxTagger/.env). A project-root .env or environment variables act as fallback
for developers who run from a checkout; the screen shows where each value
currently comes from.
"""

import asyncio
import json
import os
import webbrowser
from typing import TYPE_CHECKING

import toga
from toga.style import Pack
from toga.style.pack import COLUMN, ROW

from waxtagger import config

if TYPE_CHECKING:
    from waxtagger.app import WaxTaggerApp

DISCOGS_DEV_URL = "https://www.discogs.com/settings/developers"
SPOTIFY_DEV_URL = "https://developer.spotify.com/dashboard"

_SOURCE_LABELS = {
    "user": "from app settings",
    "project": "from project .env",
    "env": "from environment",
    None: "not set",
}


class SettingsScreen:
    def __init__(self, app: "WaxTaggerApp", first_run: bool = False):
        self.app = app
        self.first_run = first_run
        self._window: toga.Window = None
        self._inputs: dict[str, toga.TextInput] = {}
        self._source_labels: dict[str, toga.Label] = {}
        self._discogs_status: toga.Label = None
        self._spotify_status: toga.Label = None

    # ── Build ─────────────────────────────────────────────────────────────────
    # Mirrors the main screen: label column (width 110) + flex input, margin 4.

    def _field(self, key: str, label: str, secret: bool) -> toga.Box:
        widget_cls = toga.PasswordInput if secret else toga.TextInput
        inp = widget_cls(value=config.get_credential(key), placeholder=label, style=Pack(flex=1))
        src = toga.Label(_SOURCE_LABELS[config.credential_source(key)],
                         style=Pack(width=130, margin=(0, 0, 0, 8), font_size=10, color="#888888"))
        self._inputs[key] = inp
        self._source_labels[key] = src
        return toga.Box(
            children=[toga.Label(label, style=Pack(width=110, margin=(0, 8, 0, 0))), inp, src],
            style=Pack(direction=ROW, margin=4, align_items="center"),
        )

    def _section(self, title: str, url: str, rows: list, action: toga.Button, status: toga.Label) -> toga.Box:
        # Section title sits in the label column, like a form group header.
        header = toga.Box(
            children=[toga.Label(title, style=Pack(font_weight="bold", flex=1))],
            style=Pack(direction=ROW, margin=(8, 4, 0, 4)),
        )
        # Action row: status text left, buttons right (same shape as the main screen's footer).
        footer = toga.Box(
            children=[
                status,
                toga.Button("Get credentials…", on_press=lambda w, u=url: webbrowser.open(u),
                            style=Pack(margin=(0, 4, 0, 0))),
                action,
            ],
            style=Pack(direction=ROW, margin=4, align_items="center"),
        )
        return toga.Box(children=[header, *rows, footer], style=Pack(direction=COLUMN))

    def build_window(self) -> toga.Window:
        children = []

        if self.first_run:
            children.append(toga.Label(
                "WaxTagger needs API credentials for at least one source. "
                "Create a free app at Discogs and/or Spotify and paste the keys below.",
                style=Pack(margin=(8, 4, 4, 4)),
            ))

        self._discogs_status = toga.Label(self._discogs_auth_status(), style=Pack(flex=1, font_size=10, color="#888888"))
        children.append(self._section(
            "Discogs", DISCOGS_DEV_URL,
            [self._field("DISCOGS_CONSUMER_KEY", "Consumer Key", False),
             self._field("DISCOGS_CONSUMER_SECRET", "Consumer Secret", True)],
            toga.Button("Authorize…", on_press=self._on_discogs_authorize),
            self._discogs_status,
        ))

        self._spotify_status = toga.Label("", style=Pack(flex=1, font_size=10, color="#888888"))
        children.append(self._section(
            "Spotify", SPOTIFY_DEV_URL,
            [self._field("SPOTIFY_CLIENT_ID", "Client ID", False),
             self._field("SPOTIFY_CLIENT_SECRET", "Client Secret", True)],
            toga.Button("Test connection", on_press=self._on_spotify_test),
            self._spotify_status,
        ))

        children.append(toga.Divider(style=Pack(margin=(8, 4))))
        home = os.path.expanduser("~")
        shown_path = config.USER_ENV_FILE.replace(home, "~", 1)
        children.append(toga.Box(
            children=[
                toga.Label(f"Stored in {shown_path}. Empty fields fall back to the project .env / environment.",
                           style=Pack(flex=1, font_size=10, color="#888888")),
                toga.Button("Save", on_press=self._on_save),
            ],
            style=Pack(direction=ROW, margin=4, align_items="center"),
        ))

        content = toga.Box(children=children, style=Pack(direction=COLUMN, margin=8))
        self._window = toga.Window(title="WaxTagger Settings", size=(620, 330))
        self._window.content = content
        return self._window

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _discogs_auth_status(self) -> str:
        if os.path.exists(config.OAUTH_TOKEN_FILE):
            return "✓ Authorized"
        return "Discogs: not yet authorized (needed for searching)"

    def _refresh_source_labels(self):
        for key, label in self._source_labels.items():
            label.text = _SOURCE_LABELS[config.credential_source(key)]

    def _entered(self) -> dict[str, str]:
        return {key: (inp.value or "").strip() for key, inp in self._inputs.items()}

    async def _save(self) -> bool:
        try:
            config.save_credentials(self._entered())
        except OSError as e:
            await self._window.dialog(toga.ErrorDialog("Could not save", f"{config.USER_ENV_FILE}\n\n{e}"))
            return False
        self._refresh_source_labels()
        self.app.registry.reset()
        return True

    # ── Actions ───────────────────────────────────────────────────────────────

    async def _on_save(self, widget):
        if await self._save():
            await self._window.dialog(toga.InfoDialog("Saved", f"Credentials saved to\n{config.USER_ENV_FILE}"))

    async def _on_discogs_authorize(self, widget):
        if not await self._save():
            return
        if not config.has_discogs_credentials():
            await self._window.dialog(toga.InfoDialog("Missing credentials", "Enter the Discogs Consumer Key and Secret first."))
            return

        loop = asyncio.get_event_loop()
        try:
            import discogs_client as dc
            auth_client = dc.Client(
                config.DISCOGS_USER_AGENT,
                consumer_key=config.DISCOGS_CONSUMER_KEY,
                consumer_secret=config.DISCOGS_CONSUMER_SECRET,
            )
            request_token, request_secret, authorize_url = await loop.run_in_executor(
                None, auth_client.get_authorize_url
            )
        except Exception as e:
            await self._window.dialog(toga.ErrorDialog("OAuth error", str(e)))
            return

        webbrowser.open(authorize_url)
        verifier = await self._window.dialog(toga.TextInputDialog(
            title="Discogs Authorization",
            message=(f"Your browser opened:\n{authorize_url}\n\n"
                     "After authorizing, Discogs shows a verifier code.\nEnter it here:"),
        ))
        if not verifier:
            return

        try:
            auth_client._fetcher.store_token(request_token, request_secret)
            access_token, access_token_secret = await loop.run_in_executor(
                None, lambda: auth_client.get_access_token(verifier.strip())
            )
            os.makedirs(os.path.dirname(config.OAUTH_TOKEN_FILE), exist_ok=True)
            with open(config.OAUTH_TOKEN_FILE, "w") as f:
                json.dump({"access_token": access_token, "access_token_secret": access_token_secret}, f)
            os.chmod(config.OAUTH_TOKEN_FILE, 0o600)
            self._discogs_status.text = "✓ Authorized"
            self.app.registry.reset()
        except Exception as e:
            await self._window.dialog(toga.ErrorDialog("Authorization failed", str(e)))

    async def _on_spotify_test(self, widget):
        if not await self._save():
            return
        if not config.has_spotify_credentials():
            await self._window.dialog(toga.InfoDialog("Missing credentials", "Enter the Spotify Client ID and Secret first."))
            return

        self._spotify_status.text = "Testing…"
        loop = asyncio.get_event_loop()
        try:
            from waxtagger.spotify.client import SpotifyClient
            client = SpotifyClient()
            await loop.run_in_executor(None, client._ensure_token)
            self._spotify_status.text = "✓ Connected"
        except Exception as e:
            self._spotify_status.text = f"✗ {e}"
