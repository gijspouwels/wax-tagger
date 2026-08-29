"""
Shared Track model for all library sources (Music.app and folder scan).
"""

from dataclasses import dataclass
from typing import Optional

from waxtagger.utils import split_artist_title


@dataclass
class Track:
    # Current metadata
    title: str
    artist: str

    # Identity — exactly one of these is set, depending on the library source.
    persistent_id: str = ""            # Music.app track
    file_path: Optional[str] = None    # standalone file on disk

    album: Optional[str] = None
    year: Optional[int] = None
    genre: Optional[str] = None
    grouping: Optional[str] = None  # used for Label
    comment: Optional[str] = None   # used for the Discogs/Spotify URL
    track_number: Optional[int] = None  # position on the album
    track_count: Optional[int] = None   # total tracks on the album
    playlist_name: str = ""         # playlist name, or folder path in folder mode
    # True when artist/title were derived from an 'Artist - Title' or
    # '01 - Title' string because the artist tag was empty. The enricher
    # then proposes writing the cleaned values back (original_title keeps
    # the combined value).
    derived_artist_title: bool = False

    # Original values for undo
    original_album: Optional[str] = None
    original_year: Optional[int] = None
    original_genre: Optional[str] = None
    original_title: Optional[str] = None
    original_grouping: Optional[str] = None
    original_comment: Optional[str] = None

    def __post_init__(self):
        self.original_title = self.title
        if not self.artist and self.title:
            artist, title = split_artist_title(self.title)
            if title and (artist or title != self.title):
                self.artist, self.title = artist or "", title
                self.derived_artist_title = True
        self.original_album = self.album
        self.original_year = self.year
        self.original_genre = self.genre
        self.original_grouping = self.grouping
        self.original_comment = self.comment

    @property
    def is_file(self) -> bool:
        """True when this track came from a folder scan rather than Music.app."""
        return self.file_path is not None

    def __str__(self):
        return f'"{self.title}" — {self.artist}'
