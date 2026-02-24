import os

# ── .env laden (optioneel, zonder extra dependencies) ─────────────────────────
_ENV_FILE = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(_ENV_FILE):
    with open(_ENV_FILE) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                os.environ.setdefault(_k.strip(), _v.strip())

# ── Discogs OAuth credentials ──────────────────────────────────────────────────
# Aangemaakt op: https://www.discogs.com/settings/developers
DISCOGS_CONSUMER_KEY    = os.environ.get("DISCOGS_CONSUMER_KEY",    "")
DISCOGS_CONSUMER_SECRET = os.environ.get("DISCOGS_CONSUMER_SECRET", "")

# Pad waar het access token na eerste login wordt opgeslagen
OAUTH_TOKEN_FILE = os.path.join(os.path.dirname(__file__), ".oauth_tokens")

# User-agent vereist door Discogs API (app-naam + versie)
DISCOGS_USER_AGENT = "WaxTagger/1.0"

# ── Spotify API credentials ────────────────────────────────────────────────────
# Aangemaakt op: https://developer.spotify.com/dashboard
SPOTIFY_CLIENT_ID     = os.environ.get("SPOTIFY_CLIENT_ID",     "")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")

# Tijdelijke map voor artwork downloads
ARTWORK_TMP_DIR = "/tmp/artwork"

# Map voor sessielogbestanden
LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
