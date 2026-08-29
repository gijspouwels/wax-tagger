"""
Spotify Web API client voor metadata-verrijking.

Authenticatie: Client Credentials flow (geen gebruikerslogin vereist).
Token wordt in-memory gecached en automatisch ververst na 3600 seconden.
"""

import os
import re
import time
import base64
import requests
from typing import Optional

from waxtagger.models import Release
from waxtagger.utils import artist_match
from waxtagger import config


class SpotifyClient:
    _TOKEN_URL = "https://accounts.spotify.com/api/token"
    _API_BASE  = "https://api.spotify.com/v1"

    def __init__(self):
        if not (config.SPOTIFY_CLIENT_ID and config.SPOTIFY_CLIENT_SECRET):
            raise RuntimeError(
                "Spotify credentials missing: set SPOTIFY_CLIENT_ID/SECRET "
                "in Settings (keyring) or in .env"
            )
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

    _VERSION_SUFFIX_RE = re.compile(
        r'\s*[\(\[](original mix|extended mix|extended|clean extended|clean|'
        r'radio edit|club mix|instrumental|acapella|dub mix|remix|edit|mix|'
        r'version|vip|remaster|remastered|feat\..*|ft\..*|single version|'
        r'album version)[^\)\]]*[\)\]]\s*$',
        re.IGNORECASE,
    )

    def search(self, artist: str, title: str, max_results: int = 5) -> list[Release]:
        """
        Zoek op Spotify via de track-endpoint.
        """
        base_title = self._VERSION_SUFFIX_RE.sub('', title).strip()

        queries = [
            f'track:"{title}" artist:"{artist}"',
            f'track:"{base_title}" artist:"{artist}"',
            f'"{base_title}" artist:"{artist}"',
            f'"{base_title}" "{artist}"',
        ]
        seen_queries: set[str] = set()

        for q in queries:
            if q in seen_queries:
                continue
            seen_queries.add(q)

            results = [r for r in self._execute_search(q, max_results) if artist_match(artist, r.artist)]
            if results:
                return results

        return []

    def _execute_search(self, query: str, max_results: int) -> list[Release]:
        """Voer één Spotify-zoekopdracht uit en retourneer unieke albums."""
        try:
            data = self._get("search", params={
                "q": query,
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

            release = self._album_to_release(album, track_number=track.get("track_number"))
            if release:
                releases.append(release)
                if len(releases) >= max_results:
                    break

        return releases

    # ─── Release-details ───────────────────────────────────────────────────────

    def get_release_details(self, album_id: str) -> Optional[Release]:
        """
        Haal volledige albumdetails op via de Spotify Albums API.
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
        """
        if not release.artwork_url:
            return None

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

    def _album_to_release(self, album: dict, fetch_artist_genres: bool = False, track_number: Optional[int] = None) -> Optional[Release]:
        """Zet een Spotify album-object om naar een Release."""
        try:
            album_id     = album.get("id", "")
            title        = album.get("name", "")
            label        = album.get("label")
            genres       = [g.title() for g in (album.get("genres") or [])]
            total_tracks = album.get("total_tracks")

            release_date = album.get("release_date", "")
            year: Optional[int] = None
            if release_date:
                try:
                    year = int(release_date[:4])
                except ValueError:
                    pass

            artists = album.get("artists") or []
            artist  = artists[0].get("name", "") if artists else ""
            artist_id = artists[0].get("id", "") if artists else ""

            images     = album.get("images") or []
            artwork_url = self._pick_artwork(images)

            if not genres and fetch_artist_genres and artist_id:
                try:
                    artist_data = self._get(f"artists/{artist_id}")
                    genres = [g.title() for g in (artist_data.get("genres") or [])]
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
                track_number=track_number,
                total_tracks=total_tracks,
            )
        except Exception:
            return None

    @staticmethod
    def _pick_artwork(images: list[dict]) -> Optional[str]:
        """
        Kies de ~300px-variant uit de Spotify image-lijst.
        """
        if not images:
            return None
        target = 300
        best = min(images, key=lambda img: abs((img.get("width") or 0) - target))
        return best.get("url")
