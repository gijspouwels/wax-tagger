from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Track:
    # Identifier binnen Music.app (persistent ID)
    persistent_id: str

    # Huidige metadata
    title: str
    artist: str
    album: Optional[str] = None
    year: Optional[int] = None
    genre: Optional[str] = None
    grouping: Optional[str] = None  # gebruikt voor Label
    comment: Optional[str] = None   # gebruikt voor Discogs-URL
    playlist_name: str = ""

    # Originele waarden voor undo
    original_album: Optional[str] = None
    original_year: Optional[int] = None
    original_genre: Optional[str] = None
    original_title: Optional[str] = None
    original_grouping: Optional[str] = None
    original_comment: Optional[str] = None

    def __post_init__(self):
        self.original_album = self.album
        self.original_year = self.year
        self.original_genre = self.genre
        self.original_title = self.title
        self.original_grouping = self.grouping
        self.original_comment = self.comment

    def __str__(self):
        return f'"{self.title}" — {self.artist}'
