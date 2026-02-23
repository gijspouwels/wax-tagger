import os

# ── Discogs OAuth credentials ──────────────────────────────────────────────────
# Aangemaakt op: https://www.discogs.com/settings/developers
DISCOGS_CONSUMER_KEY    = os.environ.get("DISCOGS_CONSUMER_KEY",    "")
DISCOGS_CONSUMER_SECRET = os.environ.get("DISCOGS_CONSUMER_SECRET", "")

# Pad waar het access token na eerste login wordt opgeslagen
OAUTH_TOKEN_FILE = os.path.join(os.path.dirname(__file__), ".oauth_tokens")

# User-agent vereist door Discogs API (app-naam + versie)
DISCOGS_USER_AGENT = "WaxTagger/1.0"

# Tijdelijke map voor artwork downloads
ARTWORK_TMP_DIR = "/tmp/music_discogs_artwork"
