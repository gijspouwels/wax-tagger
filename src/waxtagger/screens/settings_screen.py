"""
Screen 2: Credentials management (Discogs OAuth + Spotify Client Credentials).
"""

import asyncio
import webbrowser
from typing import TYPE_CHECKING

import toga
from toga.style import Pack
from toga.style.pack import COLUMN, ROW

if TYPE_CHECKING:
    from waxtagger.app import WaxTaggerApp

_KEYRING_SERVICE = "waxtagger"


def _keyring_set(key: str, value: str):
    try:
        import keyring
        keyring.set_password(_KEYRING_SERVICE, key, value)
    except Exception:
        pass


def _keyring_get(key: str) -> str:
    try:
        import keyring
        value = keyring.get_password(_KEYRING_SERVICE, key)
        return value or ""
    except Exception:
        return ""


class SettingsScreen:
    def __init__(self, app: "WaxTaggerApp"):
        self.app = app
        self._window: toga.Window = None

        # Discogs widgets
        self._discogs_key_input: toga.TextInput = None
        self._discogs_secret_input: toga.PasswordInput = None
        self._discogs_status: toga.Label = None

        # Spotify widgets
        self._spotify_id_input: toga.TextInput = None
        self._spotify_secret_input: toga.PasswordInput = None
        self._spotify_status: toga.Label = None

    def build_window(self) -> toga.Window:
        style_row = Pack(direction=ROW, margin=6, align_items="center")
        style_label = Pack(width=120, margin=(0, 8, 0, 0))
        style_input = Pack(flex=1)
        style_section = Pack(direction=COLUMN, margin=(12, 0, 4, 0))
        style_col = Pack(direction=COLUMN, margin=12)

        # ── Discogs section ───────────────────────────────────────────────────
        self._discogs_key_input = toga.TextInput(
            placeholder="Consumer Key",
            value=_keyring_get("DISCOGS_CONSUMER_KEY"),
            style=style_input,
        )
        self._discogs_secret_input = toga.PasswordInput(
            placeholder="Consumer Secret",
            value=_keyring_get("DISCOGS_CONSUMER_SECRET"),
            style=style_input,
        )
        self._discogs_status = toga.Label(
            self._discogs_auth_status(),
            style=Pack(margin=(4, 0)),
        )
        auth_btn = toga.Button(
            "Authorize with Discogs",
            on_press=self._on_discogs_authorize,
            style=Pack(margin=(4, 0)),
        )
        discogs_box = toga.Box(
            children=[
                toga.Label("Discogs", style=Pack(font_size=14, font_weight="bold", margin=(0, 0, 4, 0))),
                toga.Box(children=[toga.Label("Consumer Key", style=style_label), self._discogs_key_input], style=style_row),
                toga.Box(children=[toga.Label("Consumer Secret", style=style_label), self._discogs_secret_input], style=style_row),
                auth_btn,
                self._discogs_status,
            ],
            style=style_section,
        )

        # ── Spotify section ───────────────────────────────────────────────────
        self._spotify_id_input = toga.TextInput(
            placeholder="Client ID",
            value=_keyring_get("SPOTIFY_CLIENT_ID"),
            style=style_input,
        )
        self._spotify_secret_input = toga.PasswordInput(
            placeholder="Client Secret",
            value=_keyring_get("SPOTIFY_CLIENT_SECRET"),
            style=style_input,
        )
        self._spotify_status = toga.Label("", style=Pack(margin=(4, 0)))
        test_btn = toga.Button(
            "Test connection",
            on_press=self._on_spotify_test,
            style=Pack(margin=(4, 0)),
        )
        spotify_box = toga.Box(
            children=[
                toga.Label("Spotify", style=Pack(font_size=14, font_weight="bold", margin=(0, 0, 4, 0))),
                toga.Box(children=[toga.Label("Client ID", style=style_label), self._spotify_id_input], style=style_row),
                toga.Box(children=[toga.Label("Client Secret", style=style_label), self._spotify_secret_input], style=style_row),
                test_btn,
                self._spotify_status,
            ],
            style=style_section,
        )

        # ── Save button ───────────────────────────────────────────────────────
        save_btn = toga.Button(
            "Save",
            on_press=self._on_save,
            style=Pack(margin=8),
        )

        content = toga.Box(
            children=[discogs_box, toga.Divider(), spotify_box, toga.Divider(), save_btn],
            style=style_col,
        )

        self._window = toga.Window(title="WaxTagger Settings", size=(500, 420))
        self._window.content = toga.ScrollContainer(content=content)
        return self._window

    # ── Auth status ───────────────────────────────────────────────────────────

    def _discogs_auth_status(self) -> str:
        import os
        from waxtagger import config
        if os.path.exists(config.OAUTH_TOKEN_FILE):
            return "✓ Discogs: Authorized"
        return "✗ Discogs: Not authorized"

    # ── Actions ───────────────────────────────────────────────────────────────

    async def _on_save(self, widget):
        _keyring_set("DISCOGS_CONSUMER_KEY", self._discogs_key_input.value or "")
        _keyring_set("DISCOGS_CONSUMER_SECRET", self._discogs_secret_input.value or "")
        _keyring_set("SPOTIFY_CLIENT_ID", self._spotify_id_input.value or "")
        _keyring_set("SPOTIFY_CLIENT_SECRET", self._spotify_secret_input.value or "")

        # Reload config module so new values take effect
        from waxtagger import config as cfg
        cfg.DISCOGS_CONSUMER_KEY    = self._discogs_key_input.value or ""
        cfg.DISCOGS_CONSUMER_SECRET = self._discogs_secret_input.value or ""
        cfg.SPOTIFY_CLIENT_ID       = self._spotify_id_input.value or ""
        cfg.SPOTIFY_CLIENT_SECRET   = self._spotify_secret_input.value or ""

        await self._window.dialog(toga.InfoDialog("Saved", "Credentials saved to keyring."))

    async def _on_discogs_authorize(self, widget):
        key    = self._discogs_key_input.value or ""
        secret = self._discogs_secret_input.value or ""
        if not key or not secret:
            await self._window.dialog(
                toga.InfoDialog("Missing credentials", "Enter Consumer Key and Secret first.")
            )
            return

        # Save credentials first
        _keyring_set("DISCOGS_CONSUMER_KEY", key)
        _keyring_set("DISCOGS_CONSUMER_SECRET", secret)
        from waxtagger import config as cfg
        cfg.DISCOGS_CONSUMER_KEY    = key
        cfg.DISCOGS_CONSUMER_SECRET = secret

        # Start OAuth flow: get authorize URL in thread, then show dialog for verifier
        loop = asyncio.get_event_loop()

        try:
            from waxtagger.discogs.client import DiscogsClient
            import discogs_client as dc

            # Build a temporary client just to get the authorize URL
            auth_client = dc.Client(
                cfg.DISCOGS_USER_AGENT,
                consumer_key=key,
                consumer_secret=secret,
            )
            request_token, request_secret, authorize_url = await loop.run_in_executor(
                None, auth_client.get_authorize_url
            )
        except Exception as e:
            await self._window.dialog(toga.ErrorDialog("OAuth error", str(e)))
            return

        webbrowser.open(authorize_url)

        verifier = await self._window.dialog(
            toga.TextInputDialog(
                title="Discogs Authorization",
                message=(
                    f"Your browser opened:\n{authorize_url}\n\n"
                    "After authorizing, Discogs shows a verifier code.\n"
                    "Enter it here:"
                ),
            )
        )
        if not verifier:
            return

        try:
            auth_client._fetcher.store_token(request_token, request_secret)
            access_token, access_token_secret = await loop.run_in_executor(
                None, lambda: auth_client.get_access_token(verifier.strip())
            )

            import json, os
            with open(cfg.OAUTH_TOKEN_FILE, "w") as f:
                json.dump({
                    "access_token": access_token,
                    "access_token_secret": access_token_secret,
                }, f)
            os.chmod(cfg.OAUTH_TOKEN_FILE, 0o600)

            self._discogs_status.text = "✓ Discogs: Authorized"
            # Reset cached discogs client so it picks up the new token
            self.app.registry._discogs = None

        except Exception as e:
            await self._window.dialog(toga.ErrorDialog("Authorization failed", str(e)))

    async def _on_spotify_test(self, widget):
        client_id     = self._spotify_id_input.value or ""
        client_secret = self._spotify_secret_input.value or ""
        if not client_id or not client_secret:
            await self._window.dialog(
                toga.InfoDialog("Missing credentials", "Enter Spotify Client ID and Secret first.")
            )
            return

        self._spotify_status.text = "Testing…"

        from waxtagger import config as cfg
        cfg.SPOTIFY_CLIENT_ID     = client_id
        cfg.SPOTIFY_CLIENT_SECRET = client_secret

        loop = asyncio.get_event_loop()
        try:
            from waxtagger.spotify.client import SpotifyClient
            client = SpotifyClient()
            await loop.run_in_executor(None, client._ensure_token)
            self._spotify_status.text = "✓ Spotify: Connected"
            # Reset cached spotify client
            self.app.registry._spotify = None
        except Exception as e:
            self._spotify_status.text = f"✗ Spotify: {e}"
