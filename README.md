# WaxTagger

Verrijkt tracks in je Apple Music/iTunes library met metadata van [Discogs](https://www.discogs.com) of [Spotify](https://open.spotify.com): album, jaartal, genre, label, artwork en de release-URL. Werkt per playlist, met een interactieve of automatische modus.

## Vereisten

- macOS met Apple Music/iTunes
- Python 3.11+
- [ffmpeg](https://ffmpeg.org) (voor MP3's met corrupte ID3-header): `brew install ffmpeg`
- Een gratis Discogs-account met een geregistreerde app (zie hieronder), en/of een Spotify Developer-app

## Installatie

```bash
git clone https://github.com/gijspouwels/wax-tagger.git
cd wax-tagger
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Discogs configureren

1. Ga naar [discogs.com/settings/developers](https://www.discogs.com/settings/developers)
2. Klik op **Create an application**
3. Vul een naam in (bijv. "WaxTagger") en sla op
4. Kopieer de **Consumer Key** en **Consumer Secret**
5. Maak een `.env`-bestand aan in de projectmap:

```
DISCOGS_CONSUMER_KEY=jouw_consumer_key
DISCOGS_CONSUMER_SECRET=jouw_consumer_secret
```

Bij de eerste keer opent automatisch een browser voor OAuth-autorisatie. Voer de verifier-code in die Discogs toont. Het access token wordt opgeslagen in `.oauth_tokens` en hoef je daarna niet meer in te voeren.

## Spotify configureren

1. Ga naar [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard)
2. Log in met je Spotify-account en klik op **Create app**
3. Vul een naam en beschrijving in; als Redirect URI kun je `http://localhost` gebruiken
4. Open de app en ga naar **Settings** → kopieer de **Client ID** en **Client Secret**
5. Voeg ze toe aan je `.env`-bestand:

```
SPOTIFY_CLIENT_ID=jouw_client_id
SPOTIFY_CLIENT_SECRET=jouw_client_secret
```

> **Let op:** WaxTagger gebruikt de *Client Credentials Flow* — er is geen browser-login of gebruikersaccount nodig. Alleen de app-credentials zijn vereist.

**Beperkingen t.o.v. Discogs:**
- Genres komen van artiestsniveau (Spotify heeft zelden genres op albumniveau); soms wat breed
- Style-tags ontbreken (Discogs-specifiek)
- Artwork is maximaal ~300px (bewuste keuze voor bestandsgrootte)

## Gebruik

```bash
.venv/bin/python3 main.py
```

### CLI-flags

Alle keuzes kunnen ook als flag worden meegegeven om interactieve prompts over te slaan:

| Flag | Omschrijving | Voorbeeld |
|---|---|---|
| `-p`, `--playlist` | Playlist naam of nummer | `-p "House"` of `-p 5` |
| `-s`, `--source` | Primaire bron: `discogs` (standaard) of `spotify` | `-s spotify` |
| `-f`, `--fields` | Te verrijken velden (kommagescheiden) | `-f "1,2,3"` of `-f "album,jaar"` |
| `-m`, `--mode` | Modus: `1`/`interactive`, `2`/`auto`, `3`/`dry` | `-m auto` |
| `-o`, `--overwrite` | Bestaande metadata overschrijven | `-o y` of `-o n` |

Zonder `-f` worden standaard **alle velden** verrijkt. Niet-opgegeven opties worden interactief gevraagd.

**Voorbeelden:**

```bash
# Discogs, volledig automatisch, alle velden, geen overwrite
.venv/bin/python3 main.py -p "Playlist Name" -s discogs -m auto -o n

# Spotify als primaire bron, dry-run
.venv/bin/python3 main.py -p House -s spotify -m dry

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

**2. Kies een metadatabron**

| Bron | Sterk in |
|---|---|
| Discogs | Vinylcollecties, uitgebreide genre/stijl-tags, labelinformatie |
| Spotify | Populaire releases, brede artiestcoverage |

Als de primaire bron niets vindt, wordt automatisch de andere bron als fallback geprobeerd.

**3. Kies een modus**

| Modus | Gedrag |
|---|---|
| Interactief | Toon kandidaten per track, kies zelf |
| Automatisch | Neem de beste match direct over |
| Dry-run | Toon wat er zou worden aangepast, schrijft niets |

**4. Bestaande metadata overschrijven?**

- **Nee** (standaard): vul alleen lege velden in
- **Ja**: overschrijf ook al-ingevulde velden

### Interactieve modus

Per track zie je de gevonden releases:

```
Track 14/47: "Get-A-Way" — Maxx

  1  ★ Get-A-Way (1993) · Blow Up · Electronic, Euro House
  2    Get-A-Way (1993) · Blow Up · Electronic, Eurodance
  3    Get-A-Way (1994) · Pulse-8 Records · Electronic, Euro House

Keuze (1/2/3 / s=skip / q=quit): 1
✓ Bijgewerkt: album, jaar, genre, label, opmerkingen, artwork
```

### URL-pinning

Als een track een Discogs- of Spotify-URL in de opmerkingen heeft, wordt die direct gebruikt zonder te zoeken:

```
# Discogs release:  https://www.discogs.com/release/12345
# Discogs master:   https://www.discogs.com/master/6789
# Spotify album:    https://open.spotify.com/album/37i9dQZF...
# Spotify track:    https://open.spotify.com/track/4iV5W9...
```

Bij een gepinde URL wordt altijd de bijbehorende client gebruikt, ongeacht de geselecteerde `--source`.

### Geen match gevonden

- **Overwrite = Nee**: track wordt overgeslagen
- **Overwrite = Ja**: genre, label (groepering) en opmerkingen worden leeggemaakt

## Weggeschreven velden

| Music.app-veld | Bron | Bestandstag |
|---|---|---|
| Album | Release-titel | — |
| Jaar | Jaar van release | — |
| Genre | Genres + styles (Discogs) / artiestgenres (Spotify) | — |
| Groepering | Label | MP3: `TPUB`, FLAC: `ORGANIZATION` |
| Opmerkingen | Release-URL (Discogs of Spotify) | — |
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
- Editor/mixer-naam wordt als artiest geprobeerd (bijv. `Underdog` uit `(Underdog Edit)`)

**Artiestnormalisatie:**
- Koppeltekens en underscores worden vervangen door spaties
- `feat.` / `ft.` / `featuring` / `presents` wordt gestript
- Komma-collaborators worden afgekapt (bijv. `Orbital` uit `Orbital, Penelope Isles`)
- Leidende prefixen `The`, `DJ`, `MC` worden gestript
- Als laatste fallback wordt het eerste woord van de artiestsnaam gebruikt

**Fallback naar andere bron:** als de gekozen bron (Discogs of Spotify) niets vindt, wordt automatisch de andere bron geprobeerd.

## Projectstructuur

```
wax-tagger/
├── main.py              # Startpunt + CLI-flow
├── config.py            # Credentials en instellingen
├── models.py            # Gemeenschappelijk Release-model
├── requirements.txt
├── .env                 # Lokale credentials (niet in git)
├── .oauth_tokens        # Discogs access token (automatisch aangemaakt, niet in git)
├── itunes/
│   ├── bridge.py        # AppleScript-communicatie met Music.app
│   └── models.py        # Track-dataclass
├── discogs/
│   ├── client.py        # Discogs API-wrapper (OAuth, zoeken, artwork)
│   └── models.py        # Re-export van Release als DiscogsRelease
└── spotify/
    └── client.py        # Spotify API-wrapper (client credentials, zoeken, artwork)
```
