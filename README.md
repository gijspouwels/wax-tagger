# WaxTagger

Verrijkt tracks in je Apple Music/iTunes library met metadata van [Discogs](https://www.discogs.com): album, jaartal, genre, label, artwork en de Discogs-release-URL. Werkt per playlist, met een interactieve of automatische modus.

## Vereisten

- macOS met Apple Music/iTunes
- Python 3.11+
- [ffmpeg](https://ffmpeg.org) (voor MP3's met corrupte ID3-header): `brew install ffmpeg`
- Een gratis Discogs-account met een geregistreerde app (zie hieronder)

## Installatie

```bash
git clone https://github.com/gijspouwels/wax-tagger.git
cd wax-tagger
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Discogs-app aanmaken

1. Ga naar [discogs.com/settings/developers](https://www.discogs.com/settings/developers)
2. Klik op **Create an application**
3. Vul een naam in (bijv. "Music Enricher") en sla op
4. Kopieer de **Consumer Key** en **Consumer Secret**
5. Vul ze in als omgevingsvariabelen (aanbevolen):

```bash
export DISCOGS_CONSUMER_KEY="jouw_consumer_key"
export DISCOGS_CONSUMER_SECRET="jouw_consumer_secret"
```

Of vul ze direct in in `config.py`:

```python
DISCOGS_CONSUMER_KEY    = "jouw_consumer_key"
DISCOGS_CONSUMER_SECRET = "jouw_consumer_secret"
```

## Gebruik

```bash
.venv/bin/python3 main.py
```

Bij de eerste keer opent automatisch een browser voor OAuth-autorisatie. Voer de verifier-code in die Discogs toont. Het access token wordt opgeslagen in `.oauth_tokens` en hoef je daarna niet meer in te voeren.

### CLI-flags

Alle keuzes kunnen ook als flag worden meegegeven om interactieve prompts over te slaan:

| Flag | Omschrijving | Voorbeeld |
|---|---|---|
| `-p`, `--playlist` | Playlist naam of nummer | `-p "House"` of `-p 5` |
| `-f`, `--fields` | Te verrijken velden (kommagescheiden) | `-f "1,2,3"` of `-f "album,jaar"` |
| `-m`, `--mode` | Modus: `1`/`interactive`, `2`/`auto`, `3`/`dry` | `-m auto` |
| `-o`, `--overwrite` | Bestaande metadata overschrijven | `-o y` of `-o n` |

Zonder `-f` worden standaard **alle velden** verrijkt. Niet-opgegeven opties worden interactief gevraagd.

**Voorbeelden:**

```bash
# Volledig automatisch, alle velden, geen overwrite
.venv/bin/python3 main.py -p "Playlist Name" -m auto -o n

# Dry-run voor een specifieke playlist
.venv/bin/python3 main.py -p House -m dry

# Alleen album en jaar bijwerken, interactief
.venv/bin/python3 main.py -p 5 -f "1,2"
```

### Stap voor stap (interactief)

**1. Kies een playlist**

```
Beschikbare playlists:
   1   House (976)
   2   Hip Hop (349)
   3   Disco (178)
   ...
Kies playlist (nummer): 2
```

**2. Kies een modus**

| Modus | Gedrag |
|---|---|
| Interactief | Toon Discogs-kandidaten per track, kies zelf |
| Automatisch | Neem de beste match direct over |
| Dry-run | Toon wat er zou worden aangepast, schrijft niets |

**3. Bestaande metadata overschrijven?**

- **Nee** (standaard): vul alleen lege velden in
- **Ja**: overschrijf ook al-ingevulde velden

### Interactieve modus

Per track zie je de gevonden Discogs-releases:

```
Track 14/47: "Get-A-Way" — Maxx

  1  ★ Get-A-Way (1993) · Blow Up · Electronic, Euro House
  2    Get-A-Way (1993) · Blow Up · Electronic, Eurodance
  3    Get-A-Way (1994) · Pulse-8 Records · Electronic, Euro House

Keuze (1/2/3 / s=skip / q=quit): 1
✓ Bijgewerkt: album, jaar, genre, label, opmerkingen, artwork
```

### Geen match gevonden

- **Overwrite = Nee**: track wordt overgeslagen
- **Overwrite = Ja**: genre, label (groepering) en opmerkingen worden leeggemaakt

## Weggeschreven velden

| Music.app-veld | Discogs-bron | Bestandstag |
|---|---|---|
| Album | Release-titel | — |
| Jaar | Jaar van release | — |
| Genre | Genres + styles | — |
| Groepering | Label | MP3: `TPUB`, FLAC: `ORGANIZATION` |
| Opmerkingen | Release-URL | — |
| Artwork | Hoes | MP3/M4A/FLAC |

Het **Label**-veld wordt zowel in Music.app (Groepering) als direct in het audiobestand opgeslagen als `TPUB`-tag, zodat Rekordbox het leest als Label.

## Logbestand

Na elke sessie wordt een JSON-logbestand aangemaakt (`enricher_DATUM_TIJD.log.json`) met per track de status en de doorgevoerde wijzigingen. Handig als je iets ongedaan wilt maken.

## Zoekstrategie

De zoekfunctie probeert automatisch meerdere varianten als een eerste zoekopdracht niets oplevert. Strategieën worden één voor één geprobeerd; bij de eerste met resultaten wordt gestopt.

**Titelbewerking:**
- Versie-suffixen worden gestript: `(Original Mix)`, `(Extended)`, `(Radio Edit)`, `(Bart Claessen Remix)`, etc.
- De laatste haakjesgroep wordt als extra fallback afgekapt, ook als die niet als standaard suffix wordt herkend (bijv. `(M&S Extended Vocal)`)
- Eerste 2 woorden uit de haakjes worden als extra zoekterm meegenomen (bijv. `Bart Claessen` uit `(Bart Claessen Remix)`)

**Artiestnormalisatie:**
- Koppeltekens en underscores worden vervangen door spaties
- `feat.` / `ft.` / `featuring` / `presents` wordt gestript
- Komma-collaborators worden afgekapt (bijv. `Orbital` uit `Orbital, Penelope Isles`)
- Leidende prefixen `The`, `DJ`, `MC` worden gestript
- Als laatste fallback wordt het eerste woord van de artiestsnaam gebruikt

## Projectstructuur

```
MusicDiscogs/
├── main.py              # Startpunt + CLI-flow
├── config.py            # Discogs-credentials en instellingen
├── requirements.txt
├── .oauth_tokens        # Opgeslagen access token (automatisch aangemaakt, niet in git)
├── itunes/
│   ├── bridge.py        # AppleScript-communicatie met Music.app
│   └── models.py        # Track-dataclass
└── discogs/
    ├── client.py        # Discogs API-wrapper (OAuth, zoeken, artwork)
    └── models.py        # DiscogsRelease-dataclass
```
