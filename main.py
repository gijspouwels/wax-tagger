#!/usr/bin/env python3
"""
WaxTagger — enriches iTunes/Music.app tracks with Discogs metadata.
"""

import sys
import os
import re
import json
import datetime
import argparse
from typing import Optional

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box
from rich.prompt import Prompt, Confirm
from rich.text import Text

import config
from itunes.bridge import check_music_running, get_playlists, get_tracks_from_playlist, update_track_metadata
from itunes.models import Track
from discogs.client import DiscogsClient
from models import Release
from utils import title_match

console = Console()

FIELDS = ["album", "year", "genre", "label", "artwork", "tracknr"]


# ─── CLI-argumenten ────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="WaxTagger — enrich iTunes tracks with Discogs metadata.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "-p", "--playlist",
        metavar="NAME_OR_NR",
        help="Playlist name or number (e.g. 'House' or '5')",
    )
    parser.add_argument(
        "-f", "--fields",
        metavar="FIELDS",
        help=(
            "Fields to enrich, comma-separated numbers or names.\n"
            f"Options: {', '.join(f'{i+1}={v}' for i, v in enumerate(FIELDS))}\n"
            "Use 'all' for all fields (default)"
        ),
    )
    parser.add_argument(
        "-m", "--mode",
        choices=["interactive", "auto", "dry"],
        metavar="MODE",
        help="interactive, auto or dry (default: interactive)",
    )
    parser.add_argument(
        "-o", "--overwrite",
        action="store_true",
        default=False,
        help="Overwrite existing metadata",
    )
    parser.add_argument(
        "-s", "--source",
        choices=["discogs", "spotify"],
        metavar="SOURCE",
        help="Primary metadata source: discogs (default) or spotify",
    )
    parser.add_argument(
        "--ignore-pinned",
        action="store_true",
        default=False,
        help="Ignore pinned URLs in comments and search instead",
    )
    parser.add_argument(
        "--clear-empty",
        action="store_true",
        default=False,
        help="Clear fields when the search result has no value for them (e.g. no genre)",
    )
    return parser.parse_args()


def _resolve_playlist_name(arg: str) -> str:
    """Zet een CLI-argument om naar een playlist-naam."""
    playlists = get_playlists()
    try:
        idx = int(arg) - 1
        if 0 <= idx < len(playlists):
            return playlists[idx]["name"]
        console.print(f"[red]Playlist number {arg} does not exist (max: {len(playlists)}).[/red]")
        sys.exit(1)
    except ValueError:
        names = [pl["name"] for pl in playlists]
        if arg in names:
            return arg
        console.print(f"[red]Playlist '{arg}' not found.[/red]")
        sys.exit(1)


def _resolve_fields(arg: str) -> set[str]:
    """Zet een CLI-argument om naar een set veldnamen."""
    if arg.strip().lower() in ("", "all"):
        return set(FIELDS)
    chosen = set()
    for part in arg.split(","):
        part = part.strip()
        try:
            idx = int(part) - 1
            if 0 <= idx < len(FIELDS):
                chosen.add(FIELDS[idx])
        except ValueError:
            if part.lower() in FIELDS:
                chosen.add(part.lower())
    return chosen if chosen else set(FIELDS)


def _resolve_mode(arg: str) -> str:
    """Zet een CLI-argument om naar een modusnaam."""
    return arg.lower() if arg.lower() in ("interactive", "auto", "dry") else "interactive"


# ─── ClientRegistry ────────────────────────────────────────────────────────────

class ClientRegistry:
    """Lazy initialisatie van metadata-clients. Elke client wordt pas aangemaakt bij eerste gebruik."""

    def __init__(self):
        self._discogs: Optional[DiscogsClient] = None
        self._spotify = None  # SpotifyClient; geïmporteerd bij gebruik

    def get_discogs(self) -> DiscogsClient:
        if self._discogs is None:
            self._discogs = DiscogsClient()
        return self._discogs

    def get_spotify(self):
        if self._spotify is None:
            from spotify.client import SpotifyClient
            self._spotify = SpotifyClient()
        return self._spotify

    def get(self, source: str):
        if source == "spotify":
            return self.get_spotify()
        return self.get_discogs()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def header():
    console.print(Panel.fit(
        "[bold cyan]WaxTagger[/bold cyan]\n"
        "[dim]Enrich your iTunes/Music library via Discogs[/dim]",
        border_style="cyan",
    ))
    console.print()


def pick_playlist() -> str:
    """Toon playlistkeuze en geef de gekozen naam terug."""
    console.print("[bold]Available playlists:[/bold]")
    playlists = get_playlists()

    if not playlists:
        console.print("[red]No playlists found in Music.app.[/red]")
        sys.exit(1)

    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    table.add_column("Nr", style="dim", width=4)
    table.add_column("Name")
    table.add_column("Tracks", justify="right", style="dim")

    for i, pl in enumerate(playlists, 1):
        table.add_row(str(i), pl["name"], str(pl["count"]))

    console.print(table)

    while True:
        raw = Prompt.ask("Choose playlist (number)")
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(playlists):
                return playlists[idx]["name"]
        except ValueError:
            pass
        console.print("[red]Invalid choice.[/red]")


def pick_fields() -> set[str]:
    """Laat de gebruiker kiezen welke velden verrijkt worden."""
    console.print("\n[bold]Which fields do you want to enrich?[/bold]")
    console.print("[dim](press Enter for all fields, or provide numbers separated by commas)[/dim]\n")

    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    table.add_column("Nr", style="dim", width=4)
    table.add_column("Field")

    for i, f in enumerate(FIELDS, 1):
        table.add_row(str(i), f.capitalize())

    console.print(table)

    raw = Prompt.ask("Fields", default="all")
    if raw.strip().lower() in ("", "all"):
        return set(FIELDS)

    chosen = set()
    for part in raw.split(","):
        part = part.strip()
        try:
            idx = int(part) - 1
            if 0 <= idx < len(FIELDS):
                chosen.add(FIELDS[idx])
        except ValueError:
            if part.lower() in FIELDS:
                chosen.add(part.lower())

    return chosen if chosen else set(FIELDS)


def pick_mode() -> str:
    """Kies interactieve of automatische modus."""
    console.print("\n[bold]Mode:[/bold]")
    console.print("  [cyan]1[/cyan]  Interactive  — confirm each match manually")
    console.print("  [cyan]2[/cyan]  Automatic    — pick best match directly")
    console.print("  [cyan]3[/cyan]  Dry run      — show what would be changed (writes nothing)")
    raw = Prompt.ask("Choice", default="1")
    return {"1": "interactive", "2": "auto", "3": "dry"}.get(raw.strip(), "interactive")


def pick_overwrite() -> bool:
    """Vraag of bestaande (niet-lege) velden overschreven mogen worden."""
    return Confirm.ask(
        "\nOverwrite existing metadata?",
        default=False,
    )


def pick_source() -> str:
    """Kies de primaire metadatabron."""
    console.print("\n[bold]Metadata source:[/bold]")
    console.print("  [cyan]1[/cyan]  Discogs  — vinyl collections, detailed genre/style tags")
    console.print("  [cyan]2[/cyan]  Spotify  — popular releases, broad artist coverage")
    raw = Prompt.ask("Choice", default="1")
    return {"1": "discogs", "2": "spotify"}.get(raw.strip(), "discogs")


# ─── Matchingscherm ────────────────────────────────────────────────────────────

def show_track_header(track: Track, index: int, total: int):
    console.rule(f"[dim]Track {index}/{total}[/dim]")
    console.print(f"[bold]{track}[/bold]")
    parts = []
    if track.album:
        parts.append(f"album: {track.album}")
    if track.year:
        parts.append(f"year: {track.year}")
    if track.genre:
        parts.append(f"genre: {track.genre}")
    if track.grouping:
        parts.append(f"label: {track.grouping}")
    if parts:
        console.print(f"[dim]Current: {' · '.join(parts)}[/dim]")
    console.print()


def show_results(results: list[Release]) -> None:
    for i, r in enumerate(results, 1):
        marker = "[bold cyan]★[/bold cyan] " if i == 1 else "  "
        year = str(r.year) if r.year else "?"
        label = f" · {r.label}" if r.label else ""
        fmt = f" [{r.format}]" if r.format else ""
        genre = f" · [dim]{r.genre_str}[/dim]" if r.genre_str else ""
        console.print(
            f"  [cyan]{i}[/cyan]  {marker}{r.title} ({year}){label}{fmt}{genre}"
        )
    console.print()


def prompt_choice(results: list[Release]) -> Optional[Release]:
    """
    Vraag de gebruiker welke release te gebruiken.
    Geeft None terug bij skip, SystemExit bij quit.
    """
    options = "/".join(str(i) for i in range(1, len(results) + 1))
    raw = Prompt.ask(
        f"Choice ([cyan]{options}[/cyan] / [yellow]s[/yellow]=skip / [red]q[/red]=quit)",
        default="1",
    )
    raw = raw.strip().lower()
    if raw == "q":
        raise SystemExit
    if raw == "s":
        return None
    try:
        idx = int(raw) - 1
        if 0 <= idx < len(results):
            return results[idx]
    except ValueError:
        pass
    return None



# ─── Kernenrichment ────────────────────────────────────────────────────────────

_DISCOGS_URL_RE = re.compile(
    r'https?://(?:www\.)?discogs\.com/(?:[a-z]{2}/)?(release|master)/(\d+)',
    re.IGNORECASE,
)
_SPOTIFY_URL_RE = re.compile(
    r'https?://open\.spotify\.com/(album|track)/([A-Za-z0-9]+)',
    re.IGNORECASE,
)

def _release_id_from_comment(comment: Optional[str]) -> Optional[tuple[str, str, str]]:
    """
    Geeft (platform, url_type, id_str) terug als de opmerking een herkende URL bevat.
    Platforms: "discogs" of "spotify"
    url_type:  "release"/"master" (Discogs) of "album"/"track" (Spotify)
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

def _clear_discogs_fields(track: Track, fields: set[str], mode: str, log: list[dict]) -> None:
    """Maak Discogs-velden leeg wanneer er geen match gevonden is en overwrite=True."""
    cleared = {}
    if "genre" in fields and track.genre:
        cleared["genre"] = {"from": track.genre, "to": ""}
    if "label" in fields and track.grouping:
        cleared["label"] = {"from": track.grouping, "to": ""}
    if track.comment:
        cleared["comments"] = {"from": track.comment, "to": ""}

    if not cleared:
        console.print("  [dim]Nothing found and nothing to clear — skipped.[/dim]\n")
        log.append({"track": str(track), "status": "not_found"})
        return

    prefix = "[dim][dry-run][/dim] " if mode == "dry" else ""
    console.print(f"  {prefix}[yellow]Not found — fields cleared: {', '.join(cleared.keys())}[/yellow]\n")

    if mode != "dry":
        from itunes.bridge import update_track_metadata
        update_track_metadata(
            track,
            new_genre="" if "genre" in cleared else None,
            new_grouping="" if "label" in cleared else None,
            new_comment="" if "comments" in cleared else None,
        )

    log.append({"track": str(track), "status": "not_found_cleared", "changes": cleared})


def enrich_track(
    track: Track,
    registry: "ClientRegistry",
    primary_source: str,
    fields: set[str],
    mode: str,
    overwrite: bool,
    ignore_pinned: bool,
    clear_empty: bool,
    log: list[dict],
) -> bool:
    """
    Zoek een track op de primaire bron en schrijf de gekozen metadata terug.
    Als de primaire bron niets vindt, wordt de andere bron als fallback gebruikt.
    Geeft True terug als er iets bijgewerkt is.
    """
    pinned = None if ignore_pinned else _release_id_from_comment(track.comment)

    if pinned:
        pin_platform, pin_type, pin_id = pinned
        client = registry.get(pin_platform)
        label_platform = pin_platform.capitalize()
        console.print(f"  [dim]{label_platform} URL found in comments — skipping search.[/dim]")
        details = client.get_details_from_pinned(pin_type, pin_id)
        if not details:
            console.print(f"  [red]Release not found via {label_platform} URL — skipped.[/red]\n")
            log.append({"track": str(track), "status": "error", "message": f"release not found via {pin_platform} comment URL"})
            return False
    else:
        details = _search_with_fallback(track, registry, primary_source, fields, mode, overwrite, log)
        if not details:
            return False

    # Bepaal wat we gaan schrijven
    new_album = None
    new_year = None
    new_genre = None
    new_grouping = None
    new_comment = None
    new_track_number = None
    new_track_count = None
    artwork_path = None

    if "album" in fields and (overwrite or not track.album):
        new_album = details.title

    if "year" in fields and (overwrite or not track.year):
        new_year = details.year

    if "genre" in fields and (overwrite or not track.genre):
        if details.genre_str:
            new_genre = details.genre_str
        elif clear_empty and track.genre:
            new_genre = ""

    if "label" in fields and (overwrite or not track.grouping):
        if details.label:
            new_grouping = details.label
        elif clear_empty and track.grouping:
            new_grouping = ""

    if overwrite or not track.comment:
        new_comment = details.source_url or None

    # tracknr: alleen van Spotify (Music.app accepteert alleen integers in dit veld)
    is_spotify = details.source_url and "spotify" in details.source_url
    if "tracknr" in fields and is_spotify and (overwrite or not track.track_number):
        if details.track_number is not None:
            new_track_number = details.track_number
            new_track_count = details.total_tracks

    if "artwork" in fields:
        artwork_source = "spotify" if details.source_url and "spotify" in details.source_url else "discogs"
        artwork_path = registry.get(artwork_source).download_artwork(details)

    # Niets te doen?
    if not any([new_album, new_year, new_genre is not None, new_grouping is not None, new_comment, new_track_number, artwork_path]):
        console.print("  [dim]Nothing changed.[/dim]\n")
        log.append({"track": str(track), "status": "no_changes"})
        return False

    if mode != "dry":
        update_track_metadata(
            track,
            new_album=new_album,
            new_year=new_year,
            new_genre=new_genre,
            new_grouping=new_grouping,
            new_comment=new_comment,
            new_track_number=new_track_number,
            new_track_count=new_track_count,
            artwork_path=artwork_path,
        )

    # Log entry
    changes = {}
    if new_album:
        changes["album"] = {"from": track.album, "to": new_album}
    if new_year:
        changes["year"] = {"from": track.year, "to": new_year}
    if new_genre is not None:
        changes["genre"] = {"from": track.genre, "to": new_genre or "(empty)"}
    if new_grouping is not None:
        changes["label"] = {"from": track.grouping, "to": new_grouping or "(empty)"}
    if new_comment:
        changes["comments"] = {"from": track.comment, "to": new_comment}
    if new_track_number is not None:
        changes["tracknr"] = {"from": track.track_number, "to": f"{new_track_number}/{new_track_count}"}
    if artwork_path:
        changes["artwork"] = "updated"

    status = "dry_run" if mode == "dry" else "updated"
    log.append({"track": str(track), "status": status, "changes": changes})

    prefix = "[dim][dry-run][/dim] " if mode == "dry" else ""
    console.print(f"  {prefix}[green]✓[/green] Updated: {', '.join(changes.keys())}\n")
    return True


def _search_with_fallback(
    track: Track,
    registry: "ClientRegistry",
    primary_source: str,
    fields: set[str],
    mode: str,
    overwrite: bool,
    log: list[dict],
) -> "Optional[Release]":
    """
    Zoekt op de primaire bron; val terug op de andere bron als er niets gevonden wordt.
    Retourneert de gekozen Release, of None als er niets gevonden of overgeslagen is.
    """
    fallback_source = "spotify" if primary_source == "discogs" else "discogs"

    for attempt, source in enumerate([primary_source, fallback_source]):
        is_fallback = (attempt > 0)
        client = registry.get(source)
        results = client.search(track.artist, track.title)

        if not results:
            if is_fallback:
                if overwrite:
                    _clear_discogs_fields(track, fields, mode, log)
                else:
                    console.print(f"  [dim]Nothing found on {primary_source.capitalize()} or {fallback_source.capitalize()} — skipped.[/dim]\n")
                    log.append({"track": str(track), "status": "not_found"})
                return None
            console.print(f"  [dim]Nothing found on {source.capitalize()} — trying {fallback_source.capitalize()}...[/dim]")
            continue

        if is_fallback:
            console.print(f"  [dim]Found via fallback ({source.capitalize()}).[/dim]")

        if mode == "interactive":
            show_results(results)
            try:
                chosen = prompt_choice(results)
            except SystemExit:
                raise
            if chosen is None:
                log.append({"track": str(track), "status": "skipped"})
                return None
        else:
            chosen = results[0]

        # Discogs-specific: zoek vroegste persing via master
        # Haal details eerst op — master_id is hier betrouwbaarder dan in zoekresultaten
        if source == "discogs":
            discogs_client = registry.get_discogs()
            details = discogs_client.get_release_details(int(chosen.release_id)) or chosen
            master_id = details.master_id or chosen.master_id
            if master_id:
                release_id = int(details.release_id)
                earliest = discogs_client.get_earliest_release_id(master_id, release_id, details.year)
                if earliest != release_id:
                    earliest_details = discogs_client.get_release_details(earliest)
                    if earliest_details and title_match(track.title, earliest_details.title):
                        console.print(f"  [dim]Earlier pressing found via master — using release #{earliest}.[/dim]")
                        details = earliest_details
                    else:
                        console.print(f"  [dim]Earlier pressing (#{earliest}) has a different title — keeping original release.[/dim]")
            return details
        else:
            details = client.get_release_details(chosen.release_id) or chosen
            # Bewaar track_number uit zoekresultaat (niet beschikbaar bij album-detail fetch)
            if details is not chosen and chosen.track_number is not None:
                details.track_number = chosen.track_number
            return details

    return None


# ─── Hoofdprogramma ────────────────────────────────────────────────────────────

def main():
    args = parse_args()
    header()

    if not check_music_running():
        console.print("[red]Music.app is not running. Start Music.app and try again.[/red]")
        sys.exit(1)

    playlist_name  = _resolve_playlist_name(args.playlist) if args.playlist else pick_playlist()
    source         = args.source if args.source else pick_source()
    fields         = _resolve_fields(args.fields)          if args.fields   else pick_fields()
    mode           = _resolve_mode(args.mode)              if args.mode     else pick_mode()

    # Controleer credentials voor de gekozen bron
    if source == "discogs":
        if not config.DISCOGS_CONSUMER_KEY or not config.DISCOGS_CONSUMER_SECRET:
            console.print(
                "[red]Discogs consumer key/secret not set![/red]\n"
                "Add [bold]DISCOGS_CONSUMER_KEY[/bold] and [bold]DISCOGS_CONSUMER_SECRET[/bold] "
                "to [bold].env[/bold] or as environment variables.\n\n"
                "Create an app at: https://www.discogs.com/settings/developers"
            )
            sys.exit(1)
    elif source == "spotify":
        if not config.SPOTIFY_CLIENT_ID or not config.SPOTIFY_CLIENT_SECRET:
            console.print(
                "[red]Spotify Client ID/Secret not set![/red]\n"
                "Add [bold]SPOTIFY_CLIENT_ID[/bold] and [bold]SPOTIFY_CLIENT_SECRET[/bold] "
                "to [bold].env[/bold] or as environment variables.\n\n"
                "Create an app at: https://developer.spotify.com/dashboard"
            )
            sys.exit(1)

    if mode == "dry":
        overwrite = True
    elif args.overwrite:
        overwrite = True
    else:
        overwrite = pick_overwrite()

    console.print(f"\n[dim]Loading tracks from '{playlist_name}'...[/dim]")
    tracks = get_tracks_from_playlist(playlist_name)
    total = len(tracks)
    console.print(f"[dim]{total} tracks found.[/dim]\n")

    registry = ClientRegistry()
    log = []
    updated = 0

    try:
        for i, track in enumerate(tracks, 1):
            show_track_header(track, i, total)
            try:
                if enrich_track(track, registry, source, fields, mode, overwrite, args.ignore_pinned, args.clear_empty, log):
                    updated += 1
            except KeyboardInterrupt:
                console.print("\n[yellow]Interrupted by user.[/yellow]")
                break
            except SystemExit:
                console.print("\n[yellow]Stopped on request.[/yellow]")
                break
            except Exception as e:
                console.print(f"  [red]Error: {e}[/red]\n")
                log.append({"track": str(track), "status": "error", "message": str(e)})

    finally:
        # Sla logbestand op
        skipped = sum(1 for e in log if e["status"] == "skipped")
        not_found = sum(1 for e in log if e["status"] == "not_found")
        cleared = sum(1 for e in log if e["status"] == "not_found_cleared")
        errors = sum(1 for e in log if e["status"] == "error")

        console.rule()
        parts = [
            f"[green]{updated}[/green] updated",
            f"[yellow]{skipped}[/yellow] skipped",
        ]
        if not_found:
            parts.append(f"[dim]{not_found} not found[/dim]")
        if cleared:
            parts.append(f"[dim]{cleared} not found (fields cleared)[/dim]")
        if errors:
            parts.append(f"[red]{errors} errors[/red]")
        console.print(f"\n[bold]Done![/bold] " + " · ".join(parts))

        os.makedirs(config.LOG_DIR, exist_ok=True)
        log_path = os.path.join(config.LOG_DIR, f"enricher_{datetime.datetime.now().strftime('%Y-%m-%d_%H%M')}.log.json")
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(log, f, ensure_ascii=False, indent=2)
        console.print(f"[dim]Log file: {log_path}[/dim]\n")


if __name__ == "__main__":
    main()
