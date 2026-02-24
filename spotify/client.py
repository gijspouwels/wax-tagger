"""
Spotify Web API client voor metadata-verrijking.

Authenticatie: Client Credentials flow (geen gebruikerslogin vereist).
Token wordt in-memory gecached en automatisch ververst na 3600 seconden.
"""

import os
import time
import base64
import requests
from typing import Optional

from models import Release
import config


class SpotifyClient:
    _TOKEN_URL = "https://accounts.spotify.com/api/token"
    _API_BASE  = "https://api.spotify.com/v1"

    def __init__(self):
        os.makedirs(config.ARTWORK_TMP_DIR, exist_ok=True)
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0.0

    # ─── Authenticatie ─────────────────────────────────────────────────────────

    def _ensure_token(self) -> None:
        """Ververs het access token als het verlopen is."""
        if self._access_token and time.time() < self._token_expires_at - 30:
            return

        credentials = f"{config.SPOTIFY_CLIENT_ID}:{config.SPOTIFY_CLIENT_SECRET}"
        encoded = base64.b64encode(credentials.encode()).decode()

        response = requests.post(
            self._TOKEN_URL,
            headers={
                "Authorization": f"Basic {encoded}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "client_credentials"},
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        self._access_token = data["access_token"]
        self._token_expires_at = time.time() + data.get("expires_in", 3600)

    def _get(self, endpoint: str, params: Optional[dict] = None) -> dict:
        """Voer een GET-verzoek uit naar de Spotify API."""
        self._ensure_token()
        response = requests.get(
            f"{self._API_BASE}/{endpoint}",
            headers={"Authorization": f"Bearer {self._access_token}"},
            params=params or {},
            timeout=15,
        )
        response.raise_for_status()
        return response.json()

    # ─── Zoeken ────────────────────────────────────────────────────────────────

    def search(self, artist: str, title: str, max_results: int = 5) -> list[Release]:
        """
        Zoek op Spotify via de track-endpoint.
        Retourneert unieke albums (op album_id gededupliceerd) als Release-objecten.
        """
        try:
            data = self._get("search", params={
                "q": f"track:{title} artist:{artist}",
                "type": "track",
                "limit": 20,
            })
        except Exception:
            return []

        tracks = data.get("tracks", {}).get("items", []) or []
        seen_albums: set[str] = set()
        releases: list[Release] = []

        for track in tracks:
            album = track.get("album") or {}
            album_id = album.get("id")
            if not album_id or album_id in seen_albums:
                continue
            seen_albums.add(album_id)

            release = self._album_to_release(album)
            if release:
                releases.append(release)
                if len(releases) >= max_results:
                    break

        return releases

    # ─── Release-details ───────────────────────────────────────────────────────

    def get_release_details(self, album_id: str) -> Optional[Release]:
        """
        Haal volledige albumdetails op via de Spotify Albums API.
        Als album.genres leeg is, worden artiestgenres gebruikt als fallback.
        """
        try:
            album = self._get(f"albums/{album_id}")
        except Exception:
            return None

        release = self._album_to_release(album, fetch_artist_genres=True)
        return release

    def get_details_from_pinned(self, url_type: str, id_str: str) -> Optional[Release]:
        """
        Haal release-details op vanuit een gepinde Spotify-URL.
        url_type: "album" of "track"
        id_str:   het Spotify ID
        """
        if url_type == "track":
            try:
                track_data = self._get(f"tracks/{id_str}")
            except Exception:
                return None
            album = track_data.get("album") or {}
            album_id = album.get("id")
            if not album_id:
                return None
        else:
            album_id = id_str

        return self.get_release_details(album_id)

    # ─── Artwork ───────────────────────────────────────────────────────────────

    def download_artwork(self, release: Release) -> Optional[str]:
        """
        Download artwork naar een tijdelijk bestand.
        Gebruikt de 300px-variant (index [1]) als die beschikbaar is.
        Geeft het lokale pad terug, of None bij mislukking.
        """
        if not release.artwork_url:
            return None

        # Controleer schijfcache
        for ext in (".jpg", ".png"):
            cached = os.path.join(config.ARTWORK_TMP_DIR, f"spotify_{release.release_id}{ext}")
            if os.path.exists(cached):
                return cached

        try:
            response = requests.get(release.artwork_url, timeout=15)
            response.raise_for_status()

            content_type = response.headers.get("Content-Type", "")
            ext = ".jpg" if "jpeg" in content_type or "jpg" in content_type else ".png"
            path = os.path.join(config.ARTWORK_TMP_DIR, f"spotify_{release.release_id}{ext}")

            with open(path, "wb") as f:
                f.write(response.content)
            return path
        except Exception:
            return None

    # ─── Interne helpers ────────────────────────────────────────────────────────

    def _album_to_release(self, album: dict, fetch_artist_genres: bool = False) -> Optional[Release]:
        """Zet een Spotify album-object om naar een Release."""
        try:
            album_id   = album.get("id", "")
            title      = album.get("name", "")
            label      = album.get("label")
            genres     = list(album.get("genres") or [])

            # Jaar: alleen het eerste 4-cijferige deel
            release_date = album.get("release_date", "")
            year: Optional[int] = None
            if release_date:
                try:
                    year = int(release_date[:4])
                except ValueError:
                    pass

            # Artiest: gebruik eerste artist uit de lijst
            artists = album.get("artists") or []
            artist  = artists[0].get("name", "") if artists else ""
            artist_id = artists[0].get("id", "") if artists else ""

            # Artwork: kies de 300px-variant; val terug op de grootste
            images     = album.get("images") or []
            artwork_url = self._pick_artwork(images)

            # Genre-fallback via artiest als het album geen genres heeft
            if not genres and fetch_artist_genres and artist_id:
                try:
                    artist_data = self._get(f"artists/{artist_id}")
                    genres = list(artist_data.get("genres") or [])
                except Exception:
                    pass

            return Release(
                release_id=album_id,
                title=title,
                artist=artist,
                year=year,
                genres=genres,
                styles=[],
                label=label,
                artwork_url=artwork_url,
                source_url=f"https://open.spotify.com/album/{album_id}",
            )
        except Exception:
            return None

    @staticmethod
    def _pick_artwork(images: list[dict]) -> Optional[str]:
        """
        Kies de ~300px-variant uit de Spotify image-lijst.
        Spotify levert doorgaans 3 formaten: ~640, ~300, ~64px.
        Valt terug op de eerste (grootste) als er geen 300px is.
        """
        if not images:
            return None
        # Zoek de afbeelding die het dichtst bij 300px ligt
        target = 300
        best = min(images, key=lambda img: abs((img.get("width") or 0) - target))
        return best.get("url")
