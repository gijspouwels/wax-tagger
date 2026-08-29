"""
Folder-brug: lees en schrijf audiobestanden direct van schijf via mutagen.

Vormt het alternatief voor itunes/bridge.py: dezelfde Track-objecten, maar de
bron is een map op de computer in plaats van een Music.app-playlist.
Ondersteunt MP3, M4A/AAC/MP4, FLAC, AIFF en WAV.
"""

import os
import re
from typing import Optional

from mutagen import File as MutagenFile
from mutagen.id3 import APIC, COMM, TALB, TCON, TDRC, TIT2, TPE1, TPUB, TRCK
from mutagen.mp4 import MP4, MP4Cover, MP4FreeForm
from mutagen.flac import FLAC, Picture

from waxtagger.track import Track
from waxtagger.utils import split_artist_title


AUDIO_EXTENSIONS = (".mp3", ".m4a", ".mp4", ".aac", ".flac", ".aiff", ".aif", ".wav")

_ID3_EXTENSIONS = (".mp3", ".aiff", ".aif", ".wav")
_MP4_EXTENSIONS = (".m4a", ".mp4", ".aac")

_MP4_LABEL_KEY = "----:com.apple.iTunes:LABEL"


# ─── Scan ──────────────────────────────────────────────────────────────────────

def list_audio_files(folder: str, recursive: bool = True) -> list[str]:
    """Geef alle ondersteunde audiobestanden in een map terug, alfabetisch gesorteerd."""
    paths: list[str] = []
    if recursive:
        for root, dirs, files in os.walk(folder):
            dirs[:] = sorted(d for d in dirs if not d.startswith("."))
            for name in files:
                if not name.startswith(".") and name.lower().endswith(AUDIO_EXTENSIONS):
                    paths.append(os.path.join(root, name))
    else:
        for name in os.listdir(folder):
            path = os.path.join(folder, name)
            if os.path.isfile(path) and not name.startswith(".") and name.lower().endswith(AUDIO_EXTENSIONS):
                paths.append(path)
    return sorted(paths)


def get_tracks_from_folder(folder: str, recursive: bool = True) -> list[Track]:
    """Lees alle audiobestanden in een map als Track-objecten."""
    tracks = []
    for path in list_audio_files(folder, recursive=recursive):
        try:
            track = read_track(path, folder)
        except Exception:
            continue  # onleesbaar bestand overslaan i.p.v. de hele batch laten falen
        if track:
            tracks.append(track)
    return tracks


def read_track(path: str, folder: str = "") -> Optional[Track]:
    """Lees één audiobestand als Track. Valt terug op de bestandsnaam als tags ontbreken."""
    ext = os.path.splitext(path)[1].lower()

    if ext in _ID3_EXTENSIONS:
        tags = _read_id3(path)
    elif ext in _MP4_EXTENSIONS:
        tags = _read_mp4(path)
    elif ext == ".flac":
        tags = _read_flac(path)
    else:
        return None

    title, artist = tags["title"], tags["artist"]
    if not title or not artist:
        guessed_artist, guessed_title = _guess_from_filename(path)
        title = title or guessed_title
        artist = artist or guessed_artist

    if not title:
        return None

    return Track(
        title=title,
        artist=artist or "",
        file_path=path,
        album=tags["album"],
        year=tags["year"],
        genre=tags["genre"],
        grouping=tags["grouping"],
        comment=tags["comment"],
        track_number=tags["track_number"],
        track_count=tags["track_count"],
        playlist_name=folder or os.path.dirname(path),
    )


def _guess_from_filename(path: str) -> tuple[Optional[str], Optional[str]]:
    """Leid (artiest, titel) af uit een 'Artiest - Titel.mp3'-bestandsnaam."""
    stem = os.path.splitext(os.path.basename(path))[0]
    return split_artist_title(stem)


# ─── Lezen per formaat ─────────────────────────────────────────────────────────

def _empty_tags() -> dict:
    return {
        "title": None, "artist": None, "album": None, "year": None,
        "genre": None, "grouping": None, "comment": None,
        "track_number": None, "track_count": None,
    }


def _parse_year(raw: Optional[str]) -> Optional[int]:
    if not raw:
        return None
    m = re.search(r"\d{4}", str(raw))
    return int(m.group()) if m else None


def _parse_track_pair(raw: Optional[str]) -> tuple[Optional[int], Optional[int]]:
    """Parse '3/12' of '3' naar (3, 12) / (3, None)."""
    if not raw:
        return None, None
    parts = str(raw).split("/")
    try:
        number = int(parts[0].strip())
    except (ValueError, IndexError):
        return None, None
    count = None
    if len(parts) > 1:
        try:
            count = int(parts[1].strip())
        except ValueError:
            count = None
    return number, count


def _read_id3(path: str) -> dict:
    tags = _empty_tags()
    try:
        # MutagenFile pakt de container correct (MP3, maar ook AIFF/WAV waar ID3
        # in een chunk zit); .tags is het ID3-object of None.
        audio = MutagenFile(path)
        id3 = audio.tags if audio is not None else None
    except Exception:
        id3 = None
    if id3 is None:
        return tags  # geen of corrupte tags: val terug op de bestandsnaam

    def text(frame_id):
        frame = id3.get(frame_id)
        if frame is None or not frame.text:
            return None
        return str(frame.text[0]).strip() or None

    tags["title"] = text("TIT2")
    tags["artist"] = text("TPE1")
    tags["album"] = text("TALB")
    tags["year"] = _parse_year(text("TDRC") or text("TYER"))
    tags["genre"] = text("TCON")
    tags["grouping"] = text("TPUB") or text("GRP1") or text("TIT1")
    tags["track_number"], tags["track_count"] = _parse_track_pair(text("TRCK"))

    comments = id3.getall("COMM")
    if comments and comments[0].text:
        tags["comment"] = str(comments[0].text[0]).strip() or None

    return tags


def _read_mp4(path: str) -> dict:
    tags = _empty_tags()
    audio = MP4(path)
    if audio.tags is None:
        return tags

    def text(key):
        value = audio.tags.get(key)
        if not value:
            return None
        return str(value[0]).strip() or None

    tags["title"] = text("\xa9nam")
    tags["artist"] = text("\xa9ART")
    tags["album"] = text("\xa9alb")
    tags["year"] = _parse_year(text("\xa9day"))
    tags["genre"] = text("\xa9gen")
    tags["comment"] = text("\xa9cmt")

    label = audio.tags.get(_MP4_LABEL_KEY)
    if label:
        raw = label[0]
        tags["grouping"] = (raw.decode("utf-8", "ignore") if isinstance(raw, bytes) else str(raw)).strip() or None
    else:
        tags["grouping"] = text("\xa9grp")

    trkn = audio.tags.get("trkn")
    if trkn:
        number, count = trkn[0][0], trkn[0][1]
        tags["track_number"] = number or None
        tags["track_count"] = count or None

    return tags


def _read_flac(path: str) -> dict:
    tags = _empty_tags()
    audio = FLAC(path)

    def text(key):
        value = audio.get(key)
        if not value:
            return None
        return str(value[0]).strip() or None

    tags["title"] = text("title")
    tags["artist"] = text("artist")
    tags["album"] = text("album")
    tags["year"] = _parse_year(text("date") or text("year"))
    tags["genre"] = text("genre")
    tags["grouping"] = text("organization") or text("label") or text("grouping")
    tags["comment"] = text("comment") or text("description")

    number, count = _parse_track_pair(text("tracknumber"))
    tags["track_number"] = number
    tags["track_count"] = count or _parse_track_pair(text("tracktotal"))[0]

    return tags


# ─── Schrijven ─────────────────────────────────────────────────────────────────

def update_track_metadata(
    track: Track,
    new_title: Optional[str] = None,
    new_artist: Optional[str] = None,
    new_album: Optional[str] = None,
    new_year: Optional[int] = None,
    new_genre: Optional[str] = None,
    new_grouping: Optional[str] = None,
    new_comment: Optional[str] = None,
    new_track_number: Optional[int] = None,
    new_track_count: Optional[int] = None,
    artwork_path: Optional[str] = None,
) -> None:
    """Schrijf nieuwe metadata rechtstreeks naar het audiobestand van deze track."""
    path = track.file_path
    if not path or not os.path.exists(path):
        raise RuntimeError(f"File not found: {path}")

    img_data: Optional[bytes] = None
    mime = "image/jpeg"
    if artwork_path and os.path.exists(artwork_path):
        with open(artwork_path, "rb") as f:
            img_data = f.read()
        mime = "image/jpeg" if artwork_path.lower().endswith((".jpg", ".jpeg")) else "image/png"

    ext = os.path.splitext(path)[1].lower()
    values = dict(
        title=new_title, artist=new_artist, album=new_album, year=new_year, genre=new_genre,
        grouping=new_grouping, comment=new_comment,
        track_number=new_track_number, track_count=new_track_count,
    )

    if ext in _ID3_EXTENSIONS:
        _write_id3(path, values, img_data, mime)
    elif ext in _MP4_EXTENSIONS:
        _write_mp4(path, values, img_data, mime)
    elif ext == ".flac":
        _write_flac(path, values, img_data, mime)
    else:
        raise RuntimeError(f"Unsupported file format: {ext}")


def _write_id3(path: str, values: dict, img_data: Optional[bytes], mime: str) -> None:
    audio = MutagenFile(path)
    if audio is None:
        raise RuntimeError(f"Unreadable audio file: {path}")
    if audio.tags is None:
        audio.add_tags()
    tags = audio.tags

    if values["title"] is not None:
        tags.setall("TIT2", [TIT2(encoding=3, text=values["title"])])
    if values["artist"] is not None:
        tags.setall("TPE1", [TPE1(encoding=3, text=values["artist"])])
    if values["album"] is not None:
        tags.setall("TALB", [TALB(encoding=3, text=values["album"])])
    if values["year"] is not None:
        tags.setall("TDRC", [TDRC(encoding=3, text=str(values["year"]))])
    if values["genre"] is not None:
        tags.setall("TCON", [TCON(encoding=3, text=values["genre"])])
    if values["grouping"] is not None:
        tags.setall("TPUB", [TPUB(encoding=3, text=values["grouping"])])
    if values["comment"] is not None:
        tags.delall("COMM")
        tags.add(COMM(encoding=3, lang="eng", desc="", text=values["comment"]))
    if values["track_number"] is not None:
        text = str(values["track_number"])
        if values["track_count"]:
            text = f"{values['track_number']}/{values['track_count']}"
        tags.setall("TRCK", [TRCK(encoding=3, text=text)])
    if img_data is not None:
        tags.delall("APIC")
        tags.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=img_data))

    audio.save(v2_version=3)


def _write_mp4(path: str, values: dict, img_data: Optional[bytes], mime: str) -> None:
    audio = MP4(path)
    if audio.tags is None:
        audio.add_tags()

    if values["title"] is not None:
        audio["\xa9nam"] = [values["title"]]
    if values["artist"] is not None:
        audio["\xa9ART"] = [values["artist"]]
    if values["album"] is not None:
        audio["\xa9alb"] = [values["album"]]
    if values["year"] is not None:
        audio["\xa9day"] = [str(values["year"])]
    if values["genre"] is not None:
        audio["\xa9gen"] = [values["genre"]]
    if values["comment"] is not None:
        audio["\xa9cmt"] = [values["comment"]]
    if values["grouping"] is not None:
        audio["\xa9grp"] = [values["grouping"]]
        audio[_MP4_LABEL_KEY] = [MP4FreeForm(values["grouping"].encode("utf-8"))]
    if values["track_number"] is not None:
        audio["trkn"] = [(values["track_number"], values["track_count"] or 0)]
    if img_data is not None:
        fmt = MP4Cover.FORMAT_JPEG if mime == "image/jpeg" else MP4Cover.FORMAT_PNG
        audio["covr"] = [MP4Cover(img_data, imageformat=fmt)]

    audio.save()


def _write_flac(path: str, values: dict, img_data: Optional[bytes], mime: str) -> None:
    audio = FLAC(path)

    if values["title"] is not None:
        audio["title"] = [values["title"]]
    if values["artist"] is not None:
        audio["artist"] = [values["artist"]]
    if values["album"] is not None:
        audio["album"] = [values["album"]]
    if values["year"] is not None:
        audio["date"] = [str(values["year"])]
    if values["genre"] is not None:
        audio["genre"] = [values["genre"]]
    if values["grouping"] is not None:
        audio["organization"] = [values["grouping"]]
    if values["comment"] is not None:
        audio["comment"] = [values["comment"]]
    if values["track_number"] is not None:
        audio["tracknumber"] = [str(values["track_number"])]
        if values["track_count"]:
            audio["tracktotal"] = [str(values["track_count"])]
    if img_data is not None:
        pic = Picture()
        pic.type = 3
        pic.mime = mime
        pic.data = img_data
        audio.clear_pictures()
        audio.add_picture(pic)

    audio.save()


# ─── Hernoemen ─────────────────────────────────────────────────────────────────

RENAME_VARIABLES = ["artist", "title", "album", "year", "genre", "label", "tracknr"]

_ILLEGAL_CHARS_RE = re.compile(r'[/\\:*?"<>|\x00-\x1f]')


def sanitize_filename(name: str) -> str:
    """Maak een string veilig als bestandsnaam."""
    cleaned = _ILLEGAL_CHARS_RE.sub("_", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().strip(".")
    return cleaned[:200]


def render_filename(pattern: str, values: dict) -> Optional[str]:
    """
    Vul een patroon als '{artist} - {title}' in met trackwaarden (zonder extensie).
    Onbekende variabelen en lege waarden worden een lege string; scheidingstekens die
    daardoor zwevend achterblijven worden opgeruimd. Geeft None terug bij leeg resultaat.
    """
    def replace(match):
        key = match.group(1).strip().lower()
        value = values.get(key)
        return "" if value in (None, "") else str(value)

    rendered = re.sub(r"\{([^{}]+)\}", replace, pattern)
    rendered = re.sub(r"\(\s*\)|\[\s*\]", "", rendered)          # lege haakjes van weggevallen waarden
    rendered = re.sub(r"(\s*[-–—]\s*){2,}", " - ", rendered)     # dubbele scheidingstekens
    rendered = rendered.strip(" -–—_.")                          # zwevend scheidingsteken aan de randen
    rendered = sanitize_filename(rendered)
    return rendered or None


def rename_file(path: str, new_stem: str) -> str:
    """
    Hernoem een bestand naar new_stem (extensie blijft behouden).
    Bij een naamconflict wordt ' (2)', ' (3)', … toegevoegd. Geeft het nieuwe pad terug.
    """
    directory, filename = os.path.split(path)
    ext = os.path.splitext(filename)[1]
    target = os.path.join(directory, new_stem + ext)

    if os.path.normcase(target) == os.path.normcase(path):
        return path

    counter = 2
    while os.path.exists(target):
        target = os.path.join(directory, f"{new_stem} ({counter}){ext}")
        counter += 1

    os.rename(path, target)
    return target
