# WaxTagger — Claude Code context

## Starten
```bash
.venv/bin/python3 main.py
# Of met flags om prompts over te slaan:
.venv/bin/python3 main.py -p "Discogs Batch" -m auto -o n
```

Vereist macOS met Music.app en een geldig `.oauth_tokens` bestand (aangemaakt na eerste OAuth-login).

## Architectuur

| Bestand | Verantwoordelijkheid |
|---|---|
| `main.py` | CLI-flow, argparse, per-track enrichment-loop |
| `config.py` | Credentials (via env vars), paden |
| `discogs/client.py` | Discogs API: OAuth, zoeken (12 strategieën), release details, artwork download |
| `discogs/models.py` | `DiscogsRelease` dataclass |
| `itunes/bridge.py` | AppleScript-brug: playlists/tracks lezen, metadata + bestandstags schrijven |
| `itunes/models.py` | `Track` dataclass |

## Belangrijke ontwerpkeuzes

- **Artwork schrijven**: niet via AppleScript (geeft error -10014), maar direct naar het audiobestand via `mutagen`. Fallback naar `ffmpeg` voor MP3's met corrupte ID3-headers.
- **Label-opslag**: dubbel weggeschreven — Music.app Groepering (zichtbaar in UI) én `TPUB` ID3-tag (leesbaar door Rekordbox).
- **AppleScript delimiter**: gebruikt `linefeed` als scheidingsteken (niet komma) om genres met komma's correct te parsen.
- **OAuth**: tokens worden alleen verwijderd bij HTTP 401; netwerk-/parsefouten laten het token intact.
- **Rate limiting**: 1 seconde tussen Discogs API-calls; 2 retry-pogingen bij lege response.

## Zoekstrategie (`discogs/client.py`)

De `search()`-methode probeert 12 strategieën op volgorde en stopt bij de eerste met resultaten. Strategieën worden deduped via een `seen`-set. Van meest naar minst specifiek:

1. Volledige titel + originele artiest
2–4. Bekende versie-suffix gestript (`(Original Mix)`, `(Extended)`, etc.) × artiestnormalisaties
5. Basistitiel + eerste 2 woorden uit haakjesblok (remix-naam)
6–7. Laatste haakjesgroep afgekapt (vangt bijv. `(M&S Extended Vocal)`)
8–9. Komma-collaborator afgekapt (`Orbital, Penelope Isles` → `Orbital`)
10–11. Leidend prefix gestript (`DJ Krust` → `Krust`, `The Wildchild Experience` → `Wildchild`)
12. Eerste 2 woorden van titel als laatste fallback

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
- Artwork niet via AppleScript proberen te schrijven.
