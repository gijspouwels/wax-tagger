# WaxTagger

Enriches tracks in your Apple Music/iTunes library with metadata from [Discogs](https://www.discogs.com) or [Spotify](https://open.spotify.com): album, year, genre, label, artwork, and release URL. Works per playlist, with an interactive or automatic mode.

![WaxTagger in action](docs/screenshot.png)

## Requirements

- macOS with Apple Music/iTunes
- Python 3.11+
- [ffmpeg](https://ffmpeg.org) (for MP3s with corrupt ID3 headers): `brew install ffmpeg`
- A free Discogs account with a registered app (see below), and/or a Spotify Developer app

## Installation

```bash
git clone https://github.com/gijspouwels/wax-tagger.git
cd wax-tagger
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Configuring Discogs

1. Go to [discogs.com/settings/developers](https://www.discogs.com/settings/developers)
2. Click **Create an application**
3. Fill in a name (e.g. "WaxTagger") and save
4. Copy the **Consumer Key** and **Consumer Secret**
5. Create a `.env` file in the project folder:

```
DISCOGS_CONSUMER_KEY=your_consumer_key
DISCOGS_CONSUMER_SECRET=your_consumer_secret
```

On first run, a browser will open automatically for OAuth authorization. Enter the verifier code shown by Discogs. The access token is saved in `.oauth_tokens` and won't need to be entered again.

## Configuring Spotify

1. Go to [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard)
2. Log in with your Spotify account and click **Create app**
3. Fill in a name and description; you can use `http://localhost` as the Redirect URI
4. Open the app and go to **Settings** → copy the **Client ID** and **Client Secret**
5. Add them to your `.env` file:

```
SPOTIFY_CLIENT_ID=your_client_id
SPOTIFY_CLIENT_SECRET=your_client_secret
```

> **Note:** WaxTagger uses the *Client Credentials Flow* — no browser login or user account is required. Only the app credentials are needed.

**Limitations compared to Discogs:**
- Genres come from the artist level (Spotify rarely has genres at the album level); can be broad
- Style tags are absent (Discogs-specific)
- Artwork is capped at ~300px (intentional choice for file size)

## Usage

```bash
.venv/bin/python3 main.py
```

### CLI flags

All choices can also be passed as flags to skip interactive prompts:

| Flag | Description | Example |
|---|---|---|
| `-p`, `--playlist` | Playlist name or number | `-p "House"` or `-p 5` |
| `-s`, `--source` | Primary source: `discogs` (default) or `spotify` | `-s spotify` |
| `-f`, `--fields` | Fields to enrich (comma-separated numbers or names), or `all` | `-f "1,2,3"` or `-f "album,year"` or `-f all` |
| `-m`, `--mode` | Mode: `interactive`, `auto`, or `dry` | `-m auto` |
| `-o`, `--overwrite` | Overwrite existing metadata (flag, no value) | `-o` |
| `--ignore-pinned` | Ignore pinned URL in comments, search instead | `--ignore-pinned` |
| `--clear-empty` | Clear fields when the search result has no value for them | `--clear-empty` |

Without `-f`, you will be asked interactively which fields to enrich. Unspecified options are asked interactively.

**Examples:**

```bash
# Discogs, fully automatic, all fields, no overwrite
.venv/bin/python3 main.py -p "Playlist Name" -s discogs -m auto -f all

# Discogs, all fields, including overwriting existing metadata
.venv/bin/python3 main.py -p "Playlist Name" -s discogs -m auto -f all -o

# Spotify as primary source, dry run
.venv/bin/python3 main.py -p House -s spotify -m dry

# Update only album and year, interactive
.venv/bin/python3 main.py -p 5 -f "1,2"
```

### Step by step (interactive)

**1. Choose a playlist**

```
Available playlists:
   1   House (976)
   2   Hip Hop (349)
   3   Disco (178)
   ...
Choose playlist (number) [1]: 2
```

**2. Choose a metadata source**

| Source | Strong at |
|---|---|
| Discogs | Vinyl collections, detailed genre/style tags, label information |
| Spotify | Popular releases, broad artist coverage |

If the primary source finds nothing, the other source is automatically tried as a fallback.

**3. Choose a mode**

| Mode | Behavior |
|---|---|
| Interactive | Show candidates per track, choose yourself |
| Automatic | Pick the best match directly |
| Dry run | Show what would be changed, writes nothing |

**4. Overwrite existing metadata?**

- **No** (default): fill in only empty fields
- **Yes**: overwrite already-filled fields as well

### Interactive mode

Per track you see the found releases:

```
Track 14/47: "Get-A-Way" — Maxx
Current: album: Get-A-Way · year: 1993

  1  ★ Get-A-Way (1993) · Blow Up · Electronic, Euro House
  2    Get-A-Way (1993) · Blow Up · Electronic, Eurodance
  3    Get-A-Way (1994) · Pulse-8 Records · Electronic, Euro House

Choice (1/2/3 / s=skip / q=quit): 1
✓ Updated: album, year, genre, label, comments, artwork
```

### URL pinning

If a track has a Discogs or Spotify URL in its comments, that release is used directly without searching:

```
# Discogs release:  https://www.discogs.com/release/12345
# Discogs master:   https://www.discogs.com/master/6789
# Spotify album:    https://open.spotify.com/album/37i9dQZF...
# Spotify track:    https://open.spotify.com/track/4iV5W9...
```

When a URL is pinned, the corresponding client is always used regardless of the selected `--source`.

### No match found

- **Overwrite = No**: track is skipped
- **Overwrite = Yes**: genre, label (grouping), and comments are cleared

## Written fields

| Music.app field | Source | File tag | Note |
|---|---|---|---|
| Album | Release title | — | |
| Year | Release year | — | |
| Genre | Genres + styles (Discogs) / artist genres (Spotify) | — | |
| Grouping | Label | MP3: `TPUB`, FLAC: `ORGANIZATION` | |
| Comments | Release URL (Discogs or Spotify) | — | |
| Artwork | Cover art | MP3/M4A/FLAC | Music.app is refreshed via `refresh` after writing |
| Track number | Position on album (X/Y) | — | Spotify only |

The **Label** field is written both to Music.app (Grouping) and directly into the audio file as a `TPUB` tag, so Rekordbox reads it as Label.

## Log file

After each session a JSON log file is created in the `logs/` folder (`logs/enricher_DATE_TIME.log.json`) with the status and changes applied per track. Useful if you want to undo something. The folder is created automatically and excluded from version control.

## Search strategy

The search function automatically tries multiple variants when an initial query returns no results. Strategies are tried one by one; the first with results wins.

**Title processing:**
- Version suffixes are stripped: `(Original Mix)`, `(Extended)`, `(Radio Edit)`, `(Bart Claessen Remix)`, etc.
- The last parenthesized group is dropped as an extra fallback, even if not recognized as a standard suffix (e.g. `(M&S Extended Vocal)`)
- The first 2 words from parentheses are used as an extra search term (e.g. `Bart Claessen` from `(Bart Claessen Remix)`)
- Editor/mixer name is tried as the artist (e.g. `Underdog` from `(Underdog Edit)`)

**Artist normalization:**
- Hyphens and underscores are replaced by spaces
- `feat.` / `ft.` / `featuring` / `presents` are stripped
- Comma-collaborators are dropped (e.g. `Orbital` from `Orbital, Penelope Isles`)
- Leading prefixes `The`, `DJ`, `MC` are stripped
- As a last resort, only the first word of the artist name is used

**Fallback to other source:** if the chosen source (Discogs or Spotify) finds nothing, the other source is tried automatically.

## Project structure

```
wax-tagger/
├── main.py              # Entry point + CLI flow
├── config.py            # Credentials and settings
├── models.py            # Shared Release model (Discogs + Spotify)
├── utils.py             # Shared helpers: artist_match, title_match
├── requirements.txt
├── docs/                # Documentation assets (screenshots)
├── logs/                # Session log files (auto-created, not in git)
├── .env                 # Local credentials (not in git)
├── .oauth_tokens        # Discogs access token (auto-created, not in git)
├── itunes/
│   ├── bridge.py        # AppleScript communication with Music.app
│   └── models.py        # Track dataclass
├── discogs/
│   ├── client.py        # Discogs API wrapper (OAuth, search, artwork)
│   └── models.py        # Re-export of Release as DiscogsRelease
└── spotify/
    └── client.py        # Spotify API wrapper (client credentials, search, artwork)
```
