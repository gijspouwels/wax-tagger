import os

# ── Paden ─────────────────────────────────────────────────────────────────────
# Dev checkout: src/waxtagger/config.py → project root is twee niveaus hoger.
# Gepackaged (Briefcase): er is geen pyproject.toml naast de package, dus
# gebruik ~/Library/Application Support/WaxTagger voor .env, tokens en logs.
_SRC_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_IS_DEV = os.path.exists(os.path.join(_SRC_ROOT, "pyproject.toml"))
_APP_SUPPORT = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "WaxTagger")
_PROJECT_ROOT = _SRC_ROOT if _IS_DEV else _APP_SUPPORT
if not _IS_DEV:
    os.makedirs(_PROJECT_ROOT, exist_ok=True)

# ── .env laden (optioneel) ────────────────────────────────────────────────────
# Volgorde: project root (dev), daarna Application Support (altijd).
for _ENV_FILE in dict.fromkeys([os.path.join(_SRC_ROOT, ".env"), os.path.join(_APP_SUPPORT, ".env")]):
    if os.path.exists(_ENV_FILE):
        with open(_ENV_FILE) as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _k, _, _v = _line.partition("=")
                    os.environ.setdefault(_k.strip(), _v.strip())

# ── Keyring helper ────────────────────────────────────────────────────────────

def get_credential(key: str) -> str:
    """Read a credential: keyring first, then env vars."""
    try:
        import keyring
        value = keyring.get_password("waxtagger", key)
        if value:
            return value
    except Exception:
        pass
    return os.environ.get(key, "")


# ── Discogs OAuth credentials ──────────────────────────────────────────────────
DISCOGS_CONSUMER_KEY    = get_credential("DISCOGS_CONSUMER_KEY")    or os.environ.get("DISCOGS_CONSUMER_KEY",    "")
DISCOGS_CONSUMER_SECRET = get_credential("DISCOGS_CONSUMER_SECRET") or os.environ.get("DISCOGS_CONSUMER_SECRET", "")

# Pad waar het access token na eerste login wordt opgeslagen
OAUTH_TOKEN_FILE = os.path.join(_PROJECT_ROOT, ".oauth_tokens")

# User-agent vereist door Discogs API (app-naam + versie)
DISCOGS_USER_AGENT = "WaxTagger/2.0"

# ── Spotify API credentials ────────────────────────────────────────────────────
SPOTIFY_CLIENT_ID     = get_credential("SPOTIFY_CLIENT_ID")     or os.environ.get("SPOTIFY_CLIENT_ID",     "")
SPOTIFY_CLIENT_SECRET = get_credential("SPOTIFY_CLIENT_SECRET") or os.environ.get("SPOTIFY_CLIENT_SECRET", "")

# Tijdelijke map voor artwork downloads
ARTWORK_TMP_DIR = "/tmp/artwork"

# Map voor sessielogbestanden
LOG_DIR = os.path.join(_PROJECT_ROOT, "logs")
