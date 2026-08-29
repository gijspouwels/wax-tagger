"""
WaxTagger — core enrichment logic, UI-agnostic.

Extracted from main.py so it can be used by both the CLI and the GUI.
No Rich, no argparse, no sys.exit.
"""

import os
import re
import json
import datetime
from dataclasses import dataclass, field
from typing import Optional, Callable

from waxtagger.models import Release
from waxtagger.track import Track
from waxtagger.itunes.bridge import update_track_metadata as _update_itunes_track
from waxtagger.folder.bridge import (
    update_track_metadata as _update_file_track,
    render_filename,
    rename_file,
)
from waxtagger.utils import title_match
from waxtagger import config


FIELDS = ["album", "year", "genre", "label", "artwork", "tracknr"]

DEFAULT_RENAME_PATTERN = "{artist} - {title}"


# ─── URL-pinning ───────────────────────────────────────────────────────────────

_DISCOGS_URL_RE = re.compile(
    r'https?://(?:www\.)?discogs\.com/(?:[a-z]{2}/)?(release|master)/(\d+)',
    re.IGNORECASE,
)
_SPOTIFY_URL_RE = re.compile(
    r'https?://open\.spotify\.com/(album|track)/([A-Za-z0-9]+)',
    re.IGNORECASE,
)


def release_id_from_comment(comment: Optional[str]) -> Optional[tuple[str, str, str]]:
    """
    Returns (platform, url_type, id_str) if the comment contains a recognized URL.
    Platforms: "discogs" or "spotify"
    url_type:  "release"/"master" (Discogs) or "album"/"track" (Spotify)
    """
    if not comment:
        return None
    m = _DISCOGS_URL_RE.search(comment)
    if m:
        return ("discogs", m.group(1).lower(), m.group(2))
    m = _SPOTIFY_URL_RE.search(comment)
    if m:
        return ("spotify", m.group(1).lower(), m.group(2))
    return None


# ─── ClientRegistry ────────────────────────────────────────────────────────────

class ClientRegistry:
    """Lazy initialisation of metadata clients."""

    def __init__(self):
        self._discogs = None
        self._spotify = None

    def get_discogs(self):
        if self._discogs is None:
            from waxtagger.discogs.client import DiscogsClient
            self._discogs = DiscogsClient()
        return self._discogs

    def get_spotify(self):
        if self._spotify is None:
            from waxtagger.spotify.client import SpotifyClient
            self._spotify = SpotifyClient()
        return self._spotify

    def get(self, source: str):
        if source == "spotify":
            return self.get_spotify()
        return self.get_discogs()


# ─── Result dataclasses ────────────────────────────────────────────────────────

@dataclass
class ProposedChange:
    field: str
    from_value: object
    to_value: object


@dataclass
class TrackResult:
    track: Track
    candidates: list[Release]
    chosen: Optional[Release]
    status: str          # "found" | "not_found" | "pinned" | "error"
    proposed_changes: list[ProposedChange]
    source_used: str
    error: Optional[str] = None
    final_chosen: Optional[Release] = None  # overridden in review screen
    skip: bool = False


# ─── Core functions ────────────────────────────────────────────────────────────

def search_with_fallback(
    track: Track,
    registry: ClientRegistry,
    primary_source: str,
    progress_callback: Optional[Callable] = None,
) -> tuple[list[Release], str]:
    """
    Search on primary source; fall back to secondary if nothing found.
    Returns (candidates, source_used).
    """
    fallback_source = "spotify" if primary_source == "discogs" else "discogs"

    for attempt, source in enumerate([primary_source, fallback_source]):
        try:
            client = registry.get(source)
        except Exception as e:
            # Primary source must work; a fallback source that can't be
            # initialised (e.g. no credentials) is simply skipped.
            if source == primary_source:
                raise
            print(f"  ⚠ Fallback source {source} unavailable: {e}")
            continue
        results = client.search(track.artist, track.title)
        if results:
            return results, source

    return [], primary_source


def build_proposed_changes(
    track: Track,
    release: Release,
    fields: set[str],
    overwrite: bool,
    clear_empty: bool,
    rename_pattern: Optional[str] = None,
) -> list[ProposedChange]:
    """
    Build the list of proposed metadata changes. Pure function, writes nothing.
    """
    changes: list[ProposedChange] = []

    # Artist/title that were split out of an 'Artist - Title' string are
    # always written back so the library no longer carries the combined value.
    if track.derived_artist_title:
        if track.artist:
            changes.append(ProposedChange("artist", "", track.artist))
        if track.title != track.original_title:
            changes.append(ProposedChange("title", track.original_title, track.title))

    if "album" in fields and (overwrite or not track.album):
        if release.title != track.album:
            changes.append(ProposedChange("album", track.album, release.title))

    if "year" in fields and (overwrite or not track.year):
        if release.year and release.year != track.year:
            changes.append(ProposedChange("year", track.year, release.year))

    if "genre" in fields and (overwrite or not track.genre):
        if release.genre_str:
            if release.genre_str != track.genre:
                changes.append(ProposedChange("genre", track.genre, release.genre_str))
        elif clear_empty and track.genre:
            changes.append(ProposedChange("genre", track.genre, ""))

    if "label" in fields and (overwrite or not track.grouping):
        if release.label:
            if release.label != track.grouping:
                changes.append(ProposedChange("label", track.grouping, release.label))
        elif clear_empty and track.grouping:
            changes.append(ProposedChange("label", track.grouping, ""))

    # Comment / source URL
    new_comment = release.source_url or None
    if new_comment and (overwrite or not track.comment):
        if new_comment != track.comment:
            changes.append(ProposedChange("comment", track.comment, new_comment))

    # tracknr: only from Spotify
    is_spotify = release.source_url and "spotify" in release.source_url
    if "tracknr" in fields and is_spotify and (overwrite or not track.track_number):
        if release.track_number is not None and release.track_number != track.track_number:
            to_val = f"{release.track_number}/{release.total_tracks}" if release.total_tracks else str(release.track_number)
            changes.append(ProposedChange("tracknr", track.track_number, to_val))

    # Artwork always proposed if in fields (can't compare binary)
    if "artwork" in fields and release.artwork_url:
        changes.append(ProposedChange("artwork", None, release.artwork_url))

    # Filename: only for tracks that live on disk, using the post-enrichment values
    if rename_pattern and track.is_file:
        rename_change = _build_rename_change(track, changes, rename_pattern)
        if rename_change:
            changes.append(rename_change)

    return changes


def _build_rename_change(
    track: Track,
    changes: list[ProposedChange],
    rename_pattern: str,
) -> Optional[ProposedChange]:
    """Propose a new filename from the pattern, filled with the values after enrichment."""
    resolved = {c.field: c.to_value for c in changes}

    track_number = track.track_number
    if "tracknr" in resolved:
        track_number = int(str(resolved["tracknr"]).split("/")[0])

    values = {
        "artist": track.artist,
        "title": track.title,
        "album": resolved.get("album", track.album),
        "year": resolved.get("year", track.year),
        "genre": resolved.get("genre", track.genre),
        "label": resolved.get("label", track.grouping),
        "tracknr": f"{track_number:02d}" if track_number else None,
    }

    new_stem = render_filename(rename_pattern, values)
    if not new_stem:
        return None

    filename = os.path.basename(track.file_path)
    current_stem, ext = os.path.splitext(filename)
    if new_stem == current_stem:
        return None

    return ProposedChange("filename", filename, new_stem + ext)


def _resolve_release(
    track: Track,
    registry: ClientRegistry,
    primary_source: str,
    ignore_pinned: bool,
) -> tuple[Optional[Release], list[Release], str, str]:
    """
    Determine the best release for a track.
    Returns (chosen, candidates, source_used, status).
    status: "pinned" | "found" | "not_found" | "error"
    """
    pinned = None if ignore_pinned else release_id_from_comment(track.comment)

    if pinned:
        pin_platform, pin_type, pin_id = pinned
        client = registry.get(pin_platform)
        details = client.get_details_from_pinned(pin_type, pin_id)
        if details:
            return details, [details], pin_platform, "pinned"
        return None, [], pin_platform, "error"

    candidates, source_used = search_with_fallback(track, registry, primary_source)
    if not candidates:
        return None, [], primary_source, "not_found"

    chosen = candidates[0]

    # Discogs: look for earliest pressing via master
    if source_used == "discogs":
        discogs_client = registry.get_discogs()
        details = discogs_client.get_release_details(int(chosen.release_id)) or chosen
        master_id = details.master_id or chosen.master_id
        if master_id:
            release_id = int(details.release_id)
            earliest = discogs_client.get_earliest_release_id(master_id, release_id, details.year)
            if earliest != release_id:
                earliest_details = discogs_client.get_release_details(earliest)
                if earliest_details and title_match(track.title, earliest_details.title):
                    details = earliest_details
        chosen = details
    else:
        client = registry.get(source_used)
        details = client.get_release_details(chosen.release_id) or chosen
        if details is not chosen and chosen.track_number is not None:
            details.track_number = chosen.track_number
        chosen = details

    return chosen, candidates, source_used, "found"


def enrich_track_auto(
    track: Track,
    registry: ClientRegistry,
    primary_source: str,
    fields: set[str],
    overwrite: bool,
    ignore_pinned: bool,
    clear_empty: bool,
    progress_callback: Optional[Callable] = None,
    rename_pattern: Optional[str] = None,
) -> TrackResult:
    """
    Find the best release for a track and build proposed changes.
    Does NOT apply any changes.
    """
    try:
        chosen, candidates, source_used, status = _resolve_release(
            track, registry, primary_source, ignore_pinned
        )

        if chosen is None:
            return TrackResult(
                track=track,
                candidates=candidates,
                chosen=None,
                status=status,
                proposed_changes=[],
                source_used=source_used,
                error="No match found" if status == "not_found" else "Failed to fetch pinned release",
            )

        proposed = build_proposed_changes(
            track, chosen, fields, overwrite, clear_empty, rename_pattern
        )

        return TrackResult(
            track=track,
            candidates=candidates,
            chosen=chosen,
            status=status,
            proposed_changes=proposed,
            source_used=source_used,
        )

    except Exception as e:
        return TrackResult(
            track=track,
            candidates=[],
            chosen=None,
            status="error",
            proposed_changes=[],
            source_used=primary_source,
            error=str(e),
        )


def apply_changes(
    result: TrackResult,
    registry: ClientRegistry,
    mode: str = "auto",
) -> dict:
    """
    Apply the changes from a TrackResult to Music.app or to the file on disk.
    Uses result.final_chosen if set (user override), otherwise result.chosen.
    mode: "auto" (write) or "dry" (skip writing).
    Returns a log dict.
    """
    release = result.final_chosen or result.chosen
    if release is None or result.skip:
        return {"track": str(result.track), "status": "skipped"}

    track = result.track
    fields_changed = {c.field for c in result.proposed_changes}

    new_title      = None
    new_artist     = None
    new_album      = None
    new_year       = None
    new_genre      = None
    new_grouping   = None
    new_comment    = None
    new_track_number = None
    new_track_count  = None
    artwork_path   = None
    new_filename   = None

    for change in result.proposed_changes:
        if change.field == "title":
            new_title = change.to_value
        elif change.field == "artist":
            new_artist = change.to_value
        elif change.field == "album":
            new_album = change.to_value
        elif change.field == "year":
            new_year = change.to_value
        elif change.field == "genre":
            new_genre = change.to_value
        elif change.field == "label":
            new_grouping = change.to_value
        elif change.field == "comment":
            new_comment = change.to_value
        elif change.field == "tracknr":
            parts = str(change.to_value).split("/")
            new_track_number = int(parts[0])
            new_track_count  = int(parts[1]) if len(parts) > 1 else None
        elif change.field == "filename":
            new_filename = change.to_value
        elif change.field == "artwork":
            if mode != "dry":
                artwork_source = "spotify" if release.source_url and "spotify" in release.source_url else "discogs"
                artwork_path = registry.get(artwork_source).download_artwork(release)

    if not any([new_title, new_artist, new_album, new_year, new_genre is not None,
                new_grouping is not None, new_comment, new_track_number,
                artwork_path, new_filename]):
        if mode == "dry" and "artwork" not in fields_changed:
            return {"track": str(track), "status": "no_changes"}

    if mode != "dry":
        writer = _update_file_track if track.is_file else _update_itunes_track
        writer(
            track,
            new_title=new_title,
            new_artist=new_artist,
            new_album=new_album,
            new_year=new_year,
            new_genre=new_genre,
            new_grouping=new_grouping,
            new_comment=new_comment,
            new_track_number=new_track_number,
            new_track_count=new_track_count,
            artwork_path=artwork_path,
        )
        # Rename last: it invalidates the path the tag writer just used
        if new_filename and track.is_file:
            new_stem = os.path.splitext(new_filename)[0]
            track.file_path = rename_file(track.file_path, new_stem)
            new_filename = os.path.basename(track.file_path)

    changes = {}
    if new_title:
        changes["title"] = {"from": track.original_title, "to": new_title}
    if new_artist:
        changes["artist"] = {"from": "", "to": new_artist}
    if new_album:
        changes["album"] = {"from": track.album, "to": new_album}
    if new_year:
        changes["year"] = {"from": track.year, "to": new_year}
    if new_genre is not None:
        changes["genre"] = {"from": track.genre, "to": new_genre or "(empty)"}
    if new_grouping is not None:
        changes["label"] = {"from": track.grouping, "to": new_grouping or "(empty)"}
    if new_comment:
        changes["comment"] = {"from": track.comment, "to": new_comment}
    if new_track_number is not None:
        changes["tracknr"] = {"from": track.track_number, "to": f"{new_track_number}/{new_track_count}"}
    if artwork_path:
        changes["artwork"] = "updated"
    if new_filename:
        original = next(c.from_value for c in result.proposed_changes if c.field == "filename")
        changes["filename"] = {"from": original, "to": new_filename}

    status = "dry_run" if mode == "dry" else "updated"
    return {"track": str(track), "status": status, "changes": changes}


def run_batch(
    tracks: list[Track],
    registry: ClientRegistry,
    primary_source: str,
    fields: set[str],
    overwrite: bool,
    ignore_pinned: bool,
    clear_empty: bool,
    progress_callback: Optional[Callable[[str, int, int], None]] = None,
    cancelled_flag: Optional[list] = None,
    rename_pattern: Optional[str] = None,
) -> list[TrackResult]:
    """
    Run enrichment for all tracks. Returns list of TrackResult (no changes applied).
    progress_callback(msg, current_index, total) called for each track.
    cancelled_flag: mutable list; set [True] to stop the batch.
    rename_pattern: filename template, e.g. "{artist} - {title}"; folder tracks only.
    """
    results = []
    total = len(tracks)

    for i, track in enumerate(tracks):
        if cancelled_flag and cancelled_flag[0]:
            break

        if progress_callback:
            progress_callback(str(track), i, total)

        result = enrich_track_auto(
            track, registry, primary_source, fields, overwrite, ignore_pinned,
            clear_empty, rename_pattern=rename_pattern,
        )
        results.append(result)

    if progress_callback:
        progress_callback("Done", total, total)

    return results


def write_log(entries: list[dict], log_dir: str) -> str:
    """Write JSON log file. Returns the path."""
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(
        log_dir,
        f"enricher_{datetime.datetime.now().strftime('%Y-%m-%d_%H%M')}.log.json"
    )
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
    return log_path
