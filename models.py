"""
Gemeenschappelijk Release-model voor alle metadata-bronnen (Discogs, Spotify, etc.).
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Release:
    release_id: str           # Universeel: Discogs int→str, Spotify album ID
    title: str                # Album/release titel
    artist: str
    year: Optional[int]
    genres: list[str] = field(default_factory=list)
    styles: list[str] = field(default_factory=list)   # Discogs only; leeg voor Spotify
    label: Optional[str] = None
    artwork_url: Optional[str] = None
    source_url: str = ""      # Canonieke URL van de release (Discogs/Spotify)
    master_id: Optional[int] = None   # Discogs only; None voor Spotify
    format: Optional[str] = None      # Discogs only; None voor Spotify
    track_number: Optional[int] = None  # Spotify only; positie van de track op het album
    total_tracks: Optional[int] = None  # Spotify only; totaal aantal tracks op het album

    @property
    def genre_str(self) -> str:
        """Geef genres en styles samen terug als kommalijst."""
        combined = self.genres + self.styles
        return ", ".join(combined) if combined else ""

    def __str__(self) -> str:
        label_str = f" · {self.label}" if self.label else ""
        year_str = str(self.year) if self.year else "?"
        return f"{self.title} ({year_str}){label_str} · {self.genre_str}"
