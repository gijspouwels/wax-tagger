#!/usr/bin/env python3
"""
WaxTagger — CLI shim. Business logic lives in src/waxtagger/.
"""

import sys
import os

# Make the src/ package available without installing
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

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

# Import from the new package
from waxtagger.enricher import (
    FIELDS,
    ClientRegistry,
    run_batch,
    apply_changes,
    write_log,
    release_id_from_comment,
    TrackResult,
)
from waxtagger.enricher import DEFAULT_RENAME_PATTERN
from waxtagger.itunes.bridge import (
    check_music_running,
    get_playlists,
    get_tracks_from_playlist,
)
from waxtagger.folder.bridge import get_tracks_from_folder, RENAME_VARIABLES
from waxtagger.track import Track
from waxtagger.models import Release
from waxtagger import config

console = Console()


# ─── CLI-argumenten ────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="WaxTagger — enrich iTunes tracks with Discogs/Spotify metadata.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("-p", "--playlist", metavar="NAME_OR_NR",
                        help="Playlist name or number (e.g. 'House' or '5')")
    parser.add_argument("-d", "--folder", metavar="PATH",
                        help="Read tracks from a folder on disk instead of a Music.app playlist")
    parser.add_argument("--no-recursive", action="store_true", default=False,
                        help="With --folder: do not scan subfolders")
    parser.add_argument("--rename", metavar="PATTERN", nargs="?",
                        const=DEFAULT_RENAME_PATTERN, default=None,
                        help=(
                            "With --folder: rename files to PATTERN\n"
                            f"(default: '{DEFAULT_RENAME_PATTERN}')\n"
                            f"Variables: {', '.join('{%s}' % v for v in RENAME_VARIABLES)}"
                        ))
    parser.add_argument("-f", "--fields", metavar="FIELDS",
                        help=(
                            "Fields to enrich, comma-separated numbers or names.\n"
                            f"Options: {', '.join(f'{i+1}={v}' for i, v in enumerate(FIELDS))}\n"
                            "Use 'all' for all fields (default)"
                        ))
    parser.add_argument("-m", "--mode", choices=["interactive", "auto", "dry"], metavar="MODE",
                        help="interactive, auto or dry (default: interactive)")
    parser.add_argument("-o", "--overwrite", action="store_true", default=False,
                        help="Overwrite existing metadata")
    parser.add_argument("-s", "--source", choices=["discogs", "spotify"], metavar="SOURCE",
                        help="Primary metadata source: discogs (default) or spotify")
    parser.add_argument("--ignore-pinned", action="store_true", default=False,
                        help="Ignore pinned URLs in comments and search instead")
    parser.add_argument("--clear-empty", action="store_true", default=False,
                        help="Clear fields when the search result has no value for them")
    return parser.parse_args()


def _resolve_playlist_name(arg: str) -> str:
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
    return arg.lower() if arg.lower() in ("interactive", "auto", "dry") else "interactive"


# ─── Interactive CLI prompts ───────────────────────────────────────────────────

def header():
    console.print(Panel.fit(
        "[bold cyan]WaxTagger[/bold cyan]\n"
        "[dim]Enrich your iTunes/Music library via Discogs[/dim]",
        border_style="cyan",
    ))
    console.print()


def pick_playlist() -> str:
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
    console.print("\n[bold]Mode:[/bold]")
    console.print("  [cyan]1[/cyan]  Automatic    — pick best match directly")
    console.print("  [cyan]2[/cyan]  Dry run      — show what would be changed (writes nothing)")
    raw = Prompt.ask("Choice", default="1")
    return {"1": "auto", "2": "dry"}.get(raw.strip(), "auto")


def pick_overwrite() -> bool:
    return Confirm.ask("\nOverwrite existing metadata?", default=False)


def pick_folder() -> str:
    while True:
        raw = Prompt.ask("Path to folder")
        path = os.path.abspath(os.path.expanduser(raw.strip().strip("'\"")))
        if os.path.isdir(path):
            return path
        console.print(f"[red]Not a folder: {path}[/red]")


def pick_library() -> Optional[str]:
    """Ask which library to use. Returns a folder path, or None for Music.app."""
    console.print("\n[bold]Where are your tracks?[/bold]")
    console.print("  [cyan]1[/cyan]  Music.app  — pick a playlist")
    console.print("  [cyan]2[/cyan]  Folder     — scan audio files on disk")
    raw = Prompt.ask("Choice", default="1")
    return pick_folder() if raw.strip() == "2" else None


def pick_rename() -> Optional[str]:
    console.print(
        f"\n[dim]Rename variables: {', '.join('{%s}' % v for v in RENAME_VARIABLES)}[/dim]"
    )
    if not Confirm.ask("Rename files based on their metadata?", default=False):
        return None
    return Prompt.ask("Filename pattern", default=DEFAULT_RENAME_PATTERN).strip() or None


def pick_source() -> str:
    console.print("\n[bold]Metadata source:[/bold]")
    console.print("  [cyan]1[/cyan]  Discogs  — vinyl collections, detailed genre/style tags")
    console.print("  [cyan]2[/cyan]  Spotify  — popular releases, broad artist coverage")
    raw = Prompt.ask("Choice", default="1")
    return {"1": "discogs", "2": "spotify"}.get(raw.strip(), "discogs")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    args = parse_args()
    header()

    if args.folder and args.playlist:
        console.print("[red]Use either --playlist or --folder, not both.[/red]")
        sys.exit(1)

    # ── Library: folder on disk, or a Music.app playlist ──────────────────────
    folder = None
    playlist_name = None

    if args.folder:
        folder = os.path.abspath(os.path.expanduser(args.folder))
        if not os.path.isdir(folder):
            console.print(f"[red]Folder not found: {folder}[/red]")
            sys.exit(1)
    elif args.playlist:
        if not check_music_running():
            console.print("[red]Music.app is not running. Start Music.app and try again.[/red]")
            sys.exit(1)
        playlist_name = _resolve_playlist_name(args.playlist)
    else:
        folder = pick_library()
        if folder is None:
            if not check_music_running():
                console.print("[red]Music.app is not running. Start Music.app and try again.[/red]")
                sys.exit(1)
            playlist_name = pick_playlist()

    rename_pattern = args.rename
    if rename_pattern and not folder:
        console.print("[red]--rename only applies to --folder mode.[/red]")
        sys.exit(1)

    source        = args.source if args.source else pick_source()
    fields        = _resolve_fields(args.fields) if args.fields else pick_fields()
    mode          = _resolve_mode(args.mode) if args.mode else pick_mode()

    # Only prompt when the folder was picked interactively; --folder implies flag-driven use
    if folder and not args.folder and rename_pattern is None:
        rename_pattern = pick_rename()

    # Credential check
    if source == "discogs":
        if not config.DISCOGS_CONSUMER_KEY or not config.DISCOGS_CONSUMER_SECRET:
            console.print(
                "[red]Discogs consumer key/secret not set![/red]\n"
                "Add [bold]DISCOGS_CONSUMER_KEY[/bold] and [bold]DISCOGS_CONSUMER_SECRET[/bold] "
                "to [bold].env[/bold] or as environment variables."
            )
            sys.exit(1)
    elif source == "spotify":
        if not config.SPOTIFY_CLIENT_ID or not config.SPOTIFY_CLIENT_SECRET:
            console.print(
                "[red]Spotify Client ID/Secret not set![/red]\n"
                "Add [bold]SPOTIFY_CLIENT_ID[/bold] and [bold]SPOTIFY_CLIENT_SECRET[/bold] "
                "to [bold].env[/bold] or as environment variables."
            )
            sys.exit(1)

    if mode == "dry":
        overwrite = True
    elif args.overwrite:
        overwrite = True
    else:
        overwrite = pick_overwrite()

    if folder:
        console.print(f"\n[dim]Scanning '{folder}'...[/dim]")
        tracks = get_tracks_from_folder(folder, recursive=not args.no_recursive)
    else:
        console.print(f"\n[dim]Loading tracks from '{playlist_name}'...[/dim]")
        tracks = get_tracks_from_playlist(playlist_name)
    total = len(tracks)
    console.print(f"[dim]{total} tracks found.[/dim]\n")

    registry = ClientRegistry()
    log = []
    updated = 0

    try:
        for i, track in enumerate(tracks, 1):
            console.rule(f"[dim]Track {i}/{total}[/dim]")
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

            try:
                from waxtagger.enricher import enrich_track_auto
                result = enrich_track_auto(
                    track, registry, source, fields, overwrite,
                    args.ignore_pinned, args.clear_empty,
                    rename_pattern=rename_pattern,
                )

                if result.status == "not_found":
                    console.print("  [dim]Nothing found — skipped.[/dim]\n")
                    log.append({"track": str(track), "status": "not_found"})
                elif result.status == "error":
                    console.print(f"  [red]Error: {result.error}[/red]\n")
                    log.append({"track": str(track), "status": "error", "message": result.error})
                elif result.chosen and result.proposed_changes:
                    # Show proposed changes
                    release = result.chosen
                    year = str(release.year) if release.year else "?"
                    console.print(f"  [cyan]★[/cyan]  {release.title} ({year})"
                                  f"{' · ' + release.label if release.label else ''}"
                                  f"{' [' + release.format + ']' if release.format else ''}")

                    fields_list = [c.field for c in result.proposed_changes]
                    prefix = "[dim][dry-run][/dim] " if mode == "dry" else ""
                    console.print(f"  {prefix}[green]✓[/green] Would update: {', '.join(fields_list)}\n")

                    entry = apply_changes(result, registry, mode=mode)
                    log.append(entry)
                    if entry.get("status") == "updated":
                        updated += 1
                else:
                    console.print("  [dim]Nothing changed.[/dim]\n")
                    log.append({"track": str(track), "status": "no_changes"})

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
        skipped   = sum(1 for e in log if e.get("status") == "skipped")
        not_found = sum(1 for e in log if e.get("status") == "not_found")
        errors    = sum(1 for e in log if e.get("status") == "error")

        console.rule()
        parts_out = [
            f"[green]{updated}[/green] updated",
            f"[yellow]{skipped}[/yellow] skipped",
        ]
        if not_found:
            parts_out.append(f"[dim]{not_found} not found[/dim]")
        if errors:
            parts_out.append(f"[red]{errors} errors[/red]")
        console.print(f"\n[bold]Done![/bold] " + " · ".join(parts_out))

        log_path = write_log(log, config.LOG_DIR)
        console.print(f"[dim]Log file: {log_path}[/dim]\n")


if __name__ == "__main__":
    main()
