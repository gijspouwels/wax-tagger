from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DiscogsRelease:
    release_id: int
    title: str           # Album/release titel
    artist: str
    year: Optional[int]
    genres: list[str] = field(default_factory=list)
    styles: list[str] = field(default_factory=list)
    label: Optional[str] = None
    artwork_url: Optional[str] = None
    master_id: Optional[int] = None
    format: Optional[str] = None  # bijv. "LP", "CD", "File"

    @property
    def url(self) -> str:
        return f"https://www.discogs.com/release/{self.release_id}"

    @property
    def genre_str(self) -> str:
        """Geef genres en styles samen terug als kommalijst."""
        combined = self.genres + self.styles
        return ", ".join(combined) if combined else ""

    def __str__(self) -> str:
        label_str = f" · {self.label}" if self.label else ""
        year_str = str(self.year) if self.year else "?"
        return f"{self.title} ({year_str}){label_str} · {self.genre_str}"
