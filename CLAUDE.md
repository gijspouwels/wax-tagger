# WaxTagger — Claude Code context

## Starten
```bash
.venv/bin/python3 main.py
# Of met flags om prompts over te slaan:
.venv/bin/python3 main.py -p "Discogs Batch" -m auto -f all
# Met overwrite:
.venv/bin/python3 main.py -p "Discogs Batch" -m auto -f all -o
```

Vereist macOS met Music.app en een geldig `.oauth_tokens` bestand (aangemaakt na eerste OAuth-login).

## Architectuur

| Bestand | Verantwoordelijkheid |
|---|---|
| `main.py` | CLI-flow, argparse, ClientRegistry, per-track enrichment-loop |
| `config.py` | Credentials: App Support `.env` (geschreven door Settings) → project `.env` → env vars; `reload()`, `save_credentials()`, `credential_source()`. Gepackaged (geen `pyproject.toml` naast `src/`) staan `.oauth_tokens` en `logs/` in `~/Library/Application Support/WaxTagger/` |
| `models.py` | Gemeenschappelijk `Release`-dataclass (Discogs + Spotify) |
| `utils.py` | `artist_match()`, `title_match()` — zoekresultaat-filtering |
| `discogs/client.py` | Discogs API: OAuth, zoeken (13 strategieën), release details, artwork download |
| `discogs/models.py` | Re-export van `Release` als `DiscogsRelease` (backwards compat) |
| `spotify/client.py` | Spotify API: client credentials, zoeken (4-query cascade), artwork download |
| `itunes/bridge.py` | AppleScript-brug: playlists/tracks lezen, metadata + bestandstags schrijven |
| `itunes/models.py` | Backwards-compat re-export van `Track` (nu in `waxtagger/track.py`) |
| `track.py` | Gemeenschappelijk `Track`-dataclass — gebruikt door beide bronnen (Music.app + map) |
| `folder/bridge.py` | Map-brug: audiobestanden op schijf scannen, tags lezen/schrijven via mutagen, bestanden hernoemen |

> Let op: paden hierboven zijn relatief aan `src/waxtagger/` (feature/gui-herstructurering); `main.py` in de root is een dunne CLI-shim.

## Belangrijke ontwerpkeuzes

- **Artwork schrijven**: niet via AppleScript (geeft error -10014), maar direct naar het audiobestand via `mutagen`. Fallback naar `ffmpeg` voor MP3's met corrupte ID3-headers. Na het schrijven roept `_refresh_track()` AppleScript `refresh t` aan zodat Music.app de nieuwe afbeelding direct toont.
- **Label-opslag**: dubbel weggeschreven — Music.app Groepering (zichtbaar in UI) én `TPUB` ID3-tag (leesbaar door Rekordbox).
- **AppleScript delimiter**: gebruikt `linefeed` als scheidingsteken (niet komma) om genres met komma's correct te parsen.
- **OAuth**: tokens worden alleen verwijderd bij HTTP 401; netwerk-/parsefouten laten het token intact.
- **Rate limiting**: 1 seconde tussen Discogs API-calls; 2 retry-pogingen bij lege response.
- **artist_match / title_match** (`utils.py`): zoekresultaten worden gefilterd op artiest (substring → token-overlap → SequenceMatcher ≥0.5). `title_match` voorkomt dat de vroegste-persing-lookup een remix vervangt door het origineel.
- **tracknr-veld**: alleen geschreven wanneer de bron Spotify is (Music.app accepteert enkel integers in het track number-veld; Discogs geeft hier geen betrouwbare data).

## Bronnen: Music.app-playlist of map op schijf

Er zijn twee libraries om tracks uit te lezen; beide leveren dezelfde `Track`-objecten aan de enricher:

- **Music.app** (`itunes/bridge.py`): leest een playlist via AppleScript, schrijft terug via AppleScript + `mutagen`. `Track.persistent_id` is gezet.
- **Map** (`folder/bridge.py`): scant audiobestanden op schijf (MP3, M4A/AAC/MP4, FLAC, AIFF, WAV), leest/schrijft tags rechtstreeks via `mutagen`. `Track.file_path` is gezet; `Track.is_file` is `True`.

De enricher kiest de schrijver op basis van `track.is_file` (`apply_changes()` in `enricher.py`). Ontbrekende titel/artiest worden bij het scannen geraden uit de bestandsnaam (`Artiest - Titel.ext`, met eventueel leidend tracknummer). Voor **beide** bronnen geldt: is de artiest leeg en bevat de titel `Artiest - Titel` (ook en/em-dash, evt. leidend tracknummer), dan splitst `Track.__post_init__` die via `utils.split_artist_title()`, zet `derived_artist_title=True`, en stelt de enricher `artist`/`title`-wijzigingen voor die worden teruggeschreven (Music.app én bestandstags).

- **CLI**: `-d/--folder PATH` (i.p.v. `-p`), `--no-recursive`, `--rename [PATRoON]`.
- **GUI**: bovenaan main_screen kies je "Folder on disk"; dan verschijnen mapkeuze + hernoem-opties.

### Bestanden hernoemen (alleen mapmodus)

Met een patroon als `{artist} - {title}` worden bestanden hernoemd op basis van de *verrijkte* metadata. Variabelen: `{artist} {title} {album} {year} {genre} {label} {tracknr}` (`RENAME_VARIABLES`). Leeg gebleven variabelen en de daardoor zwevende scheidingstekens worden opgeruimd; illegale tekens worden vervangen; bij naamconflict wordt ` (2)`, ` (3)`, … toegevoegd. De hernoeming gebeurt als laatste stap in `apply_changes()` (ná het schrijven van tags, omdat het pad daardoor verandert) en verschijnt als extra `filename`-`ProposedChange` in het reviewscherm.

## Zoekstrategie (`discogs/client.py`)

De `search()`-methode probeert 13 strategieën op volgorde en stopt bij de eerste met resultaten. Strategieën worden deduped via een `seen`-set. Van meest naar minst specifiek:

1. Volledige titel + originele artiest
2–4. Bekende versie-suffix gestript (`(Original Mix)`, `(Extended)`, etc.) × artiestnormalisaties
5. Basistititel + eerste 2 woorden uit haakjesblok (remix-naam, bijv. `Bart Claessen` uit `(Bart Claessen Remix)`)
6–7. Laatste haakjesgroep afgekapt (vangt bijv. `(M&S Extended Vocal)`) × 2 artiestnormalisaties
8–9. Komma-collaborator afgekapt (`Orbital, Penelope Isles` → `Orbital`)
10–11. Leidend prefix gestript (`DJ Krust` → `Krust`, `The Wildchild Experience` → `Wildchild`)
12. Eerste 2 woorden van titel als laatste fallback
13. Editor/mixer-naam uit haakjesblok als artiest (bijv. `Underdog` uit `(Underdog Edit)`) — filtert generieke termen als "Original", "Extended", "Radio" eruit

### Na het zoeken: vroegste persing via master
Na het kiezen van de beste match roept `enrich_track()` `get_earliest_release_id()` aan als de release een `master_id` heeft. Dit scant tot 50 versies van de master en kiest de vroegste (laagste jaar). Zo wordt een re-release uit 2005 automatisch vervangen door de originele persing uit 1992. De release-details (betere genres, hogere resolutie artwork) worden vervolgens via `get_release_details()` opgehaald, met in-memory caching per run.

## URL-pinning

Als de opmerking van een track een herkende URL bevat, wordt de zoekstap overgeslagen en die specifieke release direct gebruikt. Ondersteunde formaten:

- Discogs release: `https://www.discogs.com/release/12345`
- Discogs master: `https://www.discogs.com/master/6789` (→ `resolve_master()` voor hoofd-release-ID)
- Spotify album: `https://open.spotify.com/album/37i9dQZF...`
- Spotify track: `https://open.spotify.com/track/4iV5W9...` (→ track-details → album-ID)

`_release_id_from_comment()` in `main.py` geeft een `(platform, url_type, id_str)`-triplet terug. De juiste client wordt automatisch gekozen via `ClientRegistry`, ongeacht de `--source` instelling. Met `--ignore-pinned` wordt de URL genegeerd en gewoon gezocht.

## Testen

Geen geautomatiseerde tests. Handmatig testen via de `Discogs Batch`-playlist in Music.app, of via dry-run modus (`-m dry`) op een bestaande playlist.

Om de zoeklogica te testen zonder API-calls:
```python
from discogs.client import DiscogsClient
import re
c = DiscogsClient.__new__(DiscogsClient)
# Gebruik c._VERSION_SUFFIX_RE, c._FEAT_RE, etc. direct
```

## Wat niet te doen

- Geen `git add .` — `.oauth_tokens` staat in `.gitignore` maar bevat echte credentials.
- Niet de `ui/`-map uitbreiden — bewust leeg gelaten.
- Artwork niet via AppleScript proberen te schrijven (error -10014). `refresh t` achteraf is wel OK.
- `WaxTaggerApp.exit()` niet terugzetten naar Toga's default: de Briefcase-stub draait na `Py_Finalize` een autorelease-pool leeg die via rubicon terug in Python callt → SIGSEGV bij afsluiten. Daarom `os._exit(0)`.
- Geen keyring: ad-hoc gesignede builds krijgen bij elke rebuild een andere handtekening, dus keychain-toegang wordt steeds opnieuw geweigerd/gevraagd.
