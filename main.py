#!/usr/bin/env python3
"""
WaxTagger — verrijkt iTunes/Music.app tracks met Discogs-metadata.
"""

import sys
import os
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
from itunes.bridge import get_playlists, get_tracks_from_playlist, update_track_metadata
from itunes.models import Track
from discogs.client import DiscogsClient
from discogs.models import DiscogsRelease

console = Console()

FIELDS = ["album", "jaar", "genre", "label", "artwork", "titel"]


# ─── CLI-argumenten ────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="WaxTagger — verrijk iTunes-tracks met Discogs-metadata.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "-p", "--playlist",
        metavar="NAAM_OF_NR",
        help="Playlist naam of nummer (bijv. 'House' of '5')",
    )
    parser.add_argument(
        "-f", "--fields",
        metavar="VELDEN",
        help=(
            "Te verrijken velden, kommagescheiden nummers of namen.\n"
            f"Opties: {', '.join(f'{i+1}={v}' for i, v in enumerate(FIELDS))}\n"
            "Standaard: alle velden"
        ),
    )
    parser.add_argument(
        "-m", "--mode",
        choices=["1", "2", "3", "interactive", "auto", "dry"],
        metavar="MODUS",
        help="1/interactive, 2/auto, 3/dry (standaard: interactive)",
    )
    parser.add_argument(
        "-o", "--overwrite",
        choices=["y", "n"],
        metavar="y|n",
        help="Bestaande metadata overschrijven (y=ja, n=nee)",
    )
    return parser.parse_args()


def _resolve_playlist_name(arg: str) -> str:
    """Zet een CLI-argument om naar een playlist-naam."""
    playlists = get_playlists()
    try:
        idx = int(arg) - 1
        if 0 <= idx < len(playlists):
            return playlists[idx]["name"]
        console.print(f"[red]Playlist nummer {arg} bestaat niet (max: {len(playlists)}).[/red]")
        sys.exit(1)
    except ValueError:
        names = [pl["name"] for pl in playlists]
        if arg in names:
            return arg
        console.print(f"[red]Playlist '{arg}' niet gevonden.[/red]")
        sys.exit(1)


def _resolve_fields(arg: str) -> set[str]:
    """Zet een CLI-argument om naar een set veldnamen."""
    if arg.strip().lower() in ("", "alle", "all"):
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
    return {
        "1": "interactive", "2": "auto", "3": "dry",
        "interactive": "interactive", "auto": "auto", "dry": "dry",
    }.get(arg.lower(), "interactive")


# ─── Helpers ──────────────────────────────────────────────────────────────────

def header():
    console.print(Panel.fit(
        "[bold cyan]WaxTagger[/bold cyan]\n"
        "[dim]Verrijk je iTunes/Music library via Discogs[/dim]",
        border_style="cyan",
    ))
    console.print()


def pick_playlist() -> str:
    """Toon playlistkeuze en geef de gekozen naam terug."""
    console.print("[bold]Beschikbare playlists:[/bold]")
    playlists = get_playlists()

    if not playlists:
        console.print("[red]Geen playlists gevonden in Music.app.[/red]")
        sys.exit(1)

    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    table.add_column("Nr", style="dim", width=4)
    table.add_column("Naam")
    table.add_column("Tracks", justify="right", style="dim")

    for i, pl in enumerate(playlists, 1):
        table.add_row(str(i), pl["name"], str(pl["count"]))

    console.print(table)

    while True:
        raw = Prompt.ask("Kies playlist (nummer)")
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(playlists):
                return playlists[idx]["name"]
        except ValueError:
            pass
        console.print("[red]Ongeldige keuze.[/red]")


def pick_fields() -> set[str]:
    """Laat de gebruiker kiezen welke velden verrijkt worden."""
    console.print("\n[bold]Welke velden wil je verrijken?[/bold]")
    console.print("[dim](druk Enter voor alle velden, of geef nummers gescheiden door komma's)[/dim]\n")

    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    table.add_column("Nr", style="dim", width=4)
    table.add_column("Veld")

    for i, f in enumerate(FIELDS, 1):
        table.add_row(str(i), f.capitalize())

    console.print(table)

    raw = Prompt.ask("Velden", default="alle")
    if raw.strip().lower() in ("", "alle", "all"):
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
    console.print("\n[bold]Modus:[/bold]")
    console.print("  [cyan]1[/cyan]  Interactief  — bevestig elke match handmatig")
    console.print("  [cyan]2[/cyan]  Automatisch  — neem beste match direct over")
    console.print("  [cyan]3[/cyan]  Dry-run      — toon wat er zou worden gewijzigd (schrijft niets)")
    raw = Prompt.ask("Keuze", default="1")
    return {"1": "interactive", "2": "auto", "3": "dry"}.get(raw.strip(), "interactive")


def pick_overwrite() -> bool:
    """Vraag of bestaande (niet-lege) velden overschreven mogen worden."""
    return Confirm.ask(
        "\nBestaande metadata overschrijven?",
        default=False,
    )


# ─── Matchingscherm ────────────────────────────────────────────────────────────

def show_track_header(track: Track, index: int, total: int):
    console.rule(f"[dim]Track {index}/{total}[/dim]")
    console.print(f"[bold]{track}[/bold]")
    parts = []
    if track.album:
        parts.append(f"album: {track.album}")
    if track.year:
        parts.append(f"jaar: {track.year}")
    if track.genre:
        parts.append(f"genre: {track.genre}")
    if track.grouping:
        parts.append(f"label: {track.grouping}")
    if parts:
        console.print(f"[dim]Huidig: {' · '.join(parts)}[/dim]")
    console.print()


def show_results(results: list[DiscogsRelease]) -> None:
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


def prompt_choice(results: list[DiscogsRelease]) -> Optional[DiscogsRelease]:
    """
    Vraag de gebruiker welke release te gebruiken.
    Geeft None terug bij skip, SystemExit bij quit.
    """
    options = "/".join(str(i) for i in range(1, len(results) + 1))
    raw = Prompt.ask(
        f"Keuze ([cyan]{options}[/cyan] / [yellow]s[/yellow]=skip / [red]q[/red]=quit)",
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


def confirm_title_change(original: str, new_title: str) -> bool:
    """Vraag of een afwijkende Discogs-albumtitel als tracktitel overgenomen moet worden."""
    console.print(
        f"\n  [yellow]⚠[/yellow]  Discogs-titel wijkt af:\n"
        f"     iTunes:   [dim]{original}[/dim]\n"
        f"     Discogs:  [dim]{new_title}[/dim]"
    )
    return Confirm.ask("  Titel aanpassen?", default=False)


# ─── Kernenrichment ────────────────────────────────────────────────────────────

def _clear_discogs_fields(track: Track, fields: set[str], mode: str, log: list[dict]) -> None:
    """Maak Discogs-velden leeg wanneer er geen match gevonden is en overwrite=True."""
    cleared = {}
    if "genre" in fields and track.genre:
        cleared["genre"] = {"van": track.genre, "naar": ""}
    if "label" in fields and track.grouping:
        cleared["label"] = {"van": track.grouping, "naar": ""}
    if track.comment:
        cleared["opmerkingen"] = {"van": track.comment, "naar": ""}

    if not cleared:
        console.print("  [dim]Niets gevonden en niets te wissen — overgeslagen.[/dim]\n")
        log.append({"track": str(track), "status": "not_found"})
        return

    prefix = "[dim][dry-run][/dim] " if mode == "dry" else ""
    console.print(f"  {prefix}[yellow]Niet gevonden — velden gewist: {', '.join(cleared.keys())}[/yellow]\n")

    if mode != "dry":
        from itunes.bridge import update_track_metadata
        update_track_metadata(
            track,
            new_genre="" if "genre" in cleared else None,
            new_grouping="" if "label" in cleared else None,
            new_comment="" if "opmerkingen" in cleared else None,
        )

    log.append({"track": str(track), "status": "not_found_cleared", "changes": cleared})


def enrich_track(
    track: Track,
    discogs: DiscogsClient,
    fields: set[str],
    mode: str,
    overwrite: bool,
    log: list[dict],
) -> bool:
    """
    Zoek een track op Discogs en schrijf de gekozen metadata terug.
    Geeft True terug als er iets bijgewerkt is.
    """
    results = discogs.search(track.artist, track.title)
    if not results:
        if overwrite:
            _clear_discogs_fields(track, fields, mode, log)
            return True
        console.print("  [dim]Niets gevonden op Discogs — overgeslagen.[/dim]\n")
        log.append({"track": str(track), "status": "not_found"})
        return False

    if mode == "interactive":
        show_results(results)
        try:
            chosen = prompt_choice(results)
        except SystemExit:
            raise
        if chosen is None:
            log.append({"track": str(track), "status": "skipped"})
            return False
    else:
        chosen = results[0]

    # Haal volledige details op voor betere metadata
    details = discogs.get_release_details(chosen.release_id) or chosen

    # Bepaal wat we gaan schrijven
    new_title = None
    new_album = None
    new_year = None
    new_genre = None
    new_grouping = None
    new_comment = None
    artwork_path = None

    if "album" in fields and (overwrite or not track.album):
        new_album = details.title

    if "jaar" in fields and (overwrite or not track.year):
        new_year = details.year

    if "genre" in fields and (overwrite or not track.genre):
        new_genre = details.genre_str or None

    if "label" in fields and (overwrite or not track.grouping):
        new_grouping = details.label or None

    if overwrite or not track.comment:
        new_comment = details.url

    if "titel" in fields and details.title != track.title:
        if mode == "interactive":
            if confirm_title_change(track.title, details.title):
                new_title = details.title
        # In auto-modus passen we de titel niet automatisch aan

    if "artwork" in fields:
        artwork_path = discogs.download_artwork(details)

    # Niets te doen?
    if not any([new_title, new_album, new_year, new_genre, new_grouping, new_comment, artwork_path]):
        console.print("  [dim]Niets gewijzigd.[/dim]\n")
        log.append({"track": str(track), "status": "no_changes"})
        return False

    if mode != "dry":
        update_track_metadata(
            track,
            new_title=new_title,
            new_album=new_album,
            new_year=new_year,
            new_genre=new_genre,
            new_grouping=new_grouping,
            new_comment=new_comment,
            artwork_path=artwork_path,
        )

    # Log entry
    changes = {}
    if new_title:
        changes["titel"] = {"van": track.title, "naar": new_title}
    if new_album:
        changes["album"] = {"van": track.album, "naar": new_album}
    if new_year:
        changes["jaar"] = {"van": track.year, "naar": new_year}
    if new_genre:
        changes["genre"] = {"van": track.genre, "naar": new_genre}
    if new_grouping:
        changes["label"] = {"van": track.grouping, "naar": new_grouping}
    if new_comment:
        changes["opmerkingen"] = {"van": track.comment, "naar": new_comment}
    if artwork_path:
        changes["artwork"] = "bijgewerkt"

    status = "dry_run" if mode == "dry" else "updated"
    log.append({"track": str(track), "status": status, "changes": changes})

    prefix = "[dim][dry-run][/dim] " if mode == "dry" else ""
    console.print(f"  {prefix}[green]✓[/green] Bijgewerkt: {', '.join(changes.keys())}\n")
    return True


# ─── Hoofdprogramma ────────────────────────────────────────────────────────────

def main():
    args = parse_args()
    header()

    # Controleer Discogs OAuth-credentials
    if not config.DISCOGS_CONSUMER_KEY or not config.DISCOGS_CONSUMER_SECRET:
        console.print(
            "[red]Discogs consumer key/secret niet ingesteld![/red]\n"
            "Vul [bold]DISCOGS_CONSUMER_KEY[/bold] en [bold]DISCOGS_CONSUMER_SECRET[/bold] "
            "in [bold]config.py[/bold] of als omgevingsvariabelen.\n\n"
            "Maak een app aan op: https://www.discogs.com/settings/developers"
        )
        sys.exit(1)

    playlist_name = _resolve_playlist_name(args.playlist) if args.playlist else pick_playlist()
    fields        = _resolve_fields(args.fields)           if args.fields    else set(FIELDS)
    mode          = _resolve_mode(args.mode)               if args.mode      else pick_mode()

    if mode == "dry":
        overwrite = True
    elif args.overwrite is not None:
        overwrite = args.overwrite == "y"
    else:
        overwrite = pick_overwrite()

    console.print(f"\n[dim]Tracks laden uit '{playlist_name}'...[/dim]")
    tracks = get_tracks_from_playlist(playlist_name)
    total = len(tracks)
    console.print(f"[dim]{total} tracks gevonden.[/dim]\n")

    discogs = DiscogsClient()
    log = []
    updated = 0

    try:
        for i, track in enumerate(tracks, 1):
            show_track_header(track, i, total)
            try:
                if enrich_track(track, discogs, fields, mode, overwrite, log):
                    updated += 1
            except KeyboardInterrupt:
                console.print("\n[yellow]Onderbroken door gebruiker.[/yellow]")
                break
            except SystemExit:
                console.print("\n[yellow]Gestopt op verzoek.[/yellow]")
                break
            except Exception as e:
                console.print(f"  [red]Fout: {e}[/red]\n")
                log.append({"track": str(track), "status": "error", "message": str(e)})

    finally:
        # Sla logbestand op
        skipped = sum(1 for e in log if e["status"] == "skipped")
        not_found = sum(1 for e in log if e["status"] == "not_found")
        cleared = sum(1 for e in log if e["status"] == "not_found_cleared")
        errors = sum(1 for e in log if e["status"] == "error")

        console.rule()
        parts = [
            f"[green]{updated}[/green] bijgewerkt",
            f"[yellow]{skipped}[/yellow] overgeslagen",
        ]
        if not_found:
            parts.append(f"[dim]{not_found} niet gevonden[/dim]")
        if cleared:
            parts.append(f"[dim]{cleared} niet gevonden (velden gewist)[/dim]")
        if errors:
            parts.append(f"[red]{errors} fouten[/red]")
        console.print(f"\n[bold]Klaar![/bold] " + " · ".join(parts))

        log_path = f"enricher_{datetime.datetime.now().strftime('%Y-%m-%d_%H%M')}.log.json"
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(log, f, ensure_ascii=False, indent=2)
        console.print(f"[dim]Logbestand: {log_path}[/dim]\n")


if __name__ == "__main__":
    main()
