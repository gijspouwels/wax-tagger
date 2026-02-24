"""
AppleScript-brug naar Music.app voor het uitlezen en bijwerken van tracks.
"""

import subprocess
import os
import shutil
import tempfile
from typing import Optional
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, APIC, TPUB, error as ID3Error
from mutagen.mp4 import MP4, MP4Cover
from mutagen.flac import FLAC, Picture
from .models import Track


def _run_applescript(script: str) -> str:
    """Voer een AppleScript uit en geef de uitvoer terug."""
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"AppleScript fout: {result.stderr.strip()}")
    return result.stdout.strip()


def check_music_running() -> bool:
    """Geeft True terug als Music.app actief is."""
    script = 'tell application "System Events" to return (exists process "Music")'
    try:
        return _run_applescript(script).strip().lower() == "true"
    except RuntimeError:
        return False


def get_playlists() -> list[dict]:
    """Haal alle gebruikersplaylists op uit Music.app (naam + aantal tracks)."""
    script = """
    tell application "Music"
        set output to {}
        set userPlaylists to (every playlist whose special kind is none)
        repeat with pl in userPlaylists
            set plName to name of pl
            set trackCount to count of tracks of pl
            set end of output to (plName & "|||" & trackCount)
        end repeat
        set AppleScript's text item delimiters to linefeed
        set outputStr to output as string
        set AppleScript's text item delimiters to ""
        return outputStr
    end tell
    """
    raw = _run_applescript(script)
    if not raw:
        return []

    playlists = []
    for line in raw.splitlines():
        line = line.strip()
        if "|||" in line:
            name, count_str = line.split("|||", 1)
            try:
                count = int(count_str.strip())
            except ValueError:
                count = 0
            playlists.append({"name": name.strip(), "count": count})
    return playlists


def get_tracks_from_playlist(playlist_name: str) -> list[Track]:
    """Lees alle tracks uit een playlist."""
    script = f"""
    tell application "Music"
        set pl to playlist "{playlist_name}"
        set output to {{}}
        repeat with t in tracks of pl
            set pid to persistent ID of t
            set tTitle to name of t
            set tArtist to artist of t
            try
                set tAlbum to album of t
            on error
                set tAlbum to ""
            end try
            try
                set tYear to year of t as string
            on error
                set tYear to "0"
            end try
            try
                set tGenre to genre of t
            on error
                set tGenre to ""
            end try
            try
                set tGrouping to grouping of t
            on error
                set tGrouping to ""
            end try
            try
                set tComment to comment of t
            on error
                set tComment to ""
            end try
            try
                set tTrackNum to track number of t as string
            on error
                set tTrackNum to "0"
            end try
            try
                set tTrackCount to track count of t as string
            on error
                set tTrackCount to "0"
            end try
            set end of output to (pid & "|||" & tTitle & "|||" & tArtist & "|||" & tAlbum & "|||" & tYear & "|||" & tGenre & "|||" & tGrouping & "|||" & tComment & "|||" & tTrackNum & "|||" & tTrackCount)
        end repeat
        set AppleScript's text item delimiters to linefeed
        set outputStr to output as string
        set AppleScript's text item delimiters to ""
        return outputStr
    end tell
    """
    raw = _run_applescript(script)
    if not raw:
        return []

    tracks = []
    for line in raw.splitlines():
        line = line.strip()
        parts = line.split("|||")
        if len(parts) < 10:
            continue
        pid, title, artist, album, year_str, genre, grouping, comment, track_num_str, track_count_str = parts[:10]
        try:
            year = int(year_str.strip()) if year_str.strip() not in ("0", "") else None
        except ValueError:
            year = None
        try:
            track_number = int(track_num_str.strip()) if track_num_str.strip() not in ("0", "") else None
        except ValueError:
            track_number = None
        try:
            track_count = int(track_count_str.strip()) if track_count_str.strip() not in ("0", "") else None
        except ValueError:
            track_count = None
        tracks.append(Track(
            persistent_id=pid.strip(),
            title=title.strip(),
            artist=artist.strip(),
            album=album.strip() or None,
            year=year,
            genre=genre.strip() or None,
            grouping=grouping.strip() or None,
            comment=comment.strip() or None,
            track_number=track_number,
            track_count=track_count,
            playlist_name=playlist_name,
        ))
    return tracks


def update_track_metadata(
    track: Track,
    new_title: Optional[str] = None,
    new_album: Optional[str] = None,
    new_year: Optional[int] = None,
    new_genre: Optional[str] = None,
    new_grouping: Optional[str] = None,
    new_comment: Optional[str] = None,
    new_track_number: Optional[int] = None,
    new_track_count: Optional[int] = None,
    artwork_path: Optional[str] = None,
) -> None:
    """Schrijf nieuwe metadata terug naar een track in Music.app via persistent ID."""
    set_statements = []

    if new_title is not None:
        escaped = new_title.replace('"', '\\"')
        set_statements.append(f'set name of t to "{escaped}"')
    if new_album is not None:
        escaped = new_album.replace('"', '\\"')
        set_statements.append(f'set album of t to "{escaped}"')
    if new_year is not None:
        set_statements.append(f'set year of t to {int(new_year)}')
    if new_genre is not None:
        escaped = new_genre.replace('"', '\\"')
        set_statements.append(f'set genre of t to "{escaped}"')
    if new_grouping is not None:
        escaped = new_grouping.replace('"', '\\"')
        set_statements.append(f'set grouping of t to "{escaped}"')
    if new_comment is not None:
        escaped = new_comment.replace('"', '\\"')
        set_statements.append(f'set comment of t to "{escaped}"')
    if new_track_number is not None:
        set_statements.append(f'set track number of t to {int(new_track_number)}')
    if new_track_count is not None:
        set_statements.append(f'set track count of t to {int(new_track_count)}')

    if set_statements:
        sets = "\n            ".join(set_statements)
        script = f"""
        tell application "Music"
            set t to (first track whose persistent ID is "{track.persistent_id}")
            {sets}
        end tell
        """
        _run_applescript(script)

    needs_file_write = (artwork_path and os.path.exists(artwork_path)) or new_grouping is not None
    if needs_file_write:
        _write_file_tags(
            track.persistent_id,
            artwork_path=artwork_path if (artwork_path and os.path.exists(artwork_path)) else None,
            publisher=new_grouping,
        )

    if artwork_path and os.path.exists(artwork_path):
        _refresh_track(track.persistent_id)


def _refresh_track(persistent_id: str) -> None:
    """Dwingt Music.app de trackmetadata (inclusief artwork) opnieuw uit het bestand te laden."""
    script = f"""
    tell application "Music"
        set t to (first track whose persistent ID is "{persistent_id}")
        refresh t
    end tell
    """
    try:
        _run_applescript(script)
    except RuntimeError:
        pass  # Refresh is best-effort; fout hier is niet fataal


def _get_track_file_path(persistent_id: str) -> Optional[str]:
    """Haal het POSIX-bestandspad op van een track via AppleScript."""
    script = f"""
    tell application "Music"
        set t to (first track whose persistent ID is "{persistent_id}")
        return POSIX path of (location of t as alias)
    end tell
    """
    try:
        return _run_applescript(script).strip()
    except RuntimeError:
        return None


def _write_file_tags(
    persistent_id: str,
    artwork_path: Optional[str] = None,
    publisher: Optional[str] = None,
) -> None:
    """
    Schrijf artwork en/of publisher (TPUB) direct naar het audiobestand via mutagen.
    Ondersteunt MP3, M4A/AAC en FLAC. MP3 met corrupte ID3-header valt terug op ffmpeg.
    """
    file_path = _get_track_file_path(persistent_id)
    if not file_path or not os.path.exists(file_path):
        raise RuntimeError(f"Bestand niet gevonden voor track {persistent_id}")

    ext = os.path.splitext(file_path)[1].lower()

    img_data: Optional[bytes] = None
    mime = "image/jpeg"
    if artwork_path:
        with open(artwork_path, "rb") as f:
            img_data = f.read()
        mime = "image/jpeg" if artwork_path.lower().endswith(".jpg") else "image/png"

    if ext == ".mp3":
        try:
            audio = MP3(file_path)
            if audio.tags is None:
                audio.add_tags()
            if img_data is not None:
                audio.tags.delall("APIC")
                audio.tags.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=img_data))
            if publisher is not None:
                audio.tags.delall("TPUB")
                audio.tags.add(TPUB(encoding=3, text=publisher))
            audio.save(v2_version=3)
        except Exception:
            # Fallback: ffmpeg voor bestanden met corrupte ID3-header
            _write_file_tags_ffmpeg(file_path, artwork_path=artwork_path, publisher=publisher)

    elif ext in (".m4a", ".aac", ".mp4"):
        audio = MP4(file_path)
        if img_data is not None:
            fmt = MP4Cover.FORMAT_JPEG if mime == "image/jpeg" else MP4Cover.FORMAT_PNG
            audio["covr"] = [MP4Cover(img_data, imageformat=fmt)]
        # M4A heeft geen standaard publisher-veld; sla over (Rekordbox leest dit niet)
        audio.save()

    elif ext == ".flac":
        audio = FLAC(file_path)
        if img_data is not None:
            pic = Picture()
            pic.type = 3
            pic.mime = mime
            pic.data = img_data
            audio.clear_pictures()
            audio.add_picture(pic)
        if publisher is not None:
            audio["organization"] = [publisher]  # Vorbis-comment voor label/publisher
        audio.save()

    else:
        raise RuntimeError(f"Niet-ondersteund bestandsformaat voor file-tags: {ext}")


def _write_file_tags_ffmpeg(
    file_path: str,
    artwork_path: Optional[str] = None,
    publisher: Optional[str] = None,
) -> None:
    """
    Schrijf artwork en/of publisher via ffmpeg — fallback voor MP3's met corrupte ID3-header.
    ffmpeg kopieert de audiostream zonder re-encoding en vervangt het originele bestand.
    """
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".mp3")
    os.close(tmp_fd)
    try:
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", file_path]

        if artwork_path:
            cmd += ["-i", artwork_path,
                    "-map", "0:a", "-map", "1:v",
                    "-c:a", "copy", "-c:v", "mjpeg",
                    "-metadata:s:v", "title=Album cover",
                    "-metadata:s:v", "comment=Cover (front)"]
        else:
            cmd += ["-map", "0:a", "-c:a", "copy"]

        if publisher is not None:
            cmd += ["-metadata", f"publisher={publisher}"]

        cmd += ["-id3v2_version", "3", tmp_path]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg fout: {result.stderr.strip()}")
        shutil.move(tmp_path, file_path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
