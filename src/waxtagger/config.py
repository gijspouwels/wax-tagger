"""
Configuration: credentials and paths.

Credentials are resolved, in order of precedence:
  1. the user config file  ~/Library/Application Support/WaxTagger/.env
     (written by the app's Settings screen; also usable by hand)
  2. the project-root .env (developer checkout / self-built app)
  3. environment variables

Call ``reload()`` after changing any of these at runtime.
"""

import os
from typing import Optional

CREDENTIAL_KEYS = (
    "DISCOGS_CONSUMER_KEY",
    "DISCOGS_CONSUMER_SECRET",
    "SPOTIFY_CLIENT_ID",
    "SPOTIFY_CLIENT_SECRET",
)

# ── Paths ─────────────────────────────────────────────────────────────────────
# Dev checkout: src/waxtagger/config.py → project root is two levels up.
# Packaged (Briefcase): no pyproject.toml next to the package, so all state
# lives in ~/Library/Application Support/WaxTagger.
_SRC_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
IS_DEV = os.path.exists(os.path.join(_SRC_ROOT, "pyproject.toml"))
APP_SUPPORT_DIR = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "WaxTagger")
_PROJECT_ROOT = _SRC_ROOT if IS_DEV else APP_SUPPORT_DIR

PROJECT_ENV_FILE = os.path.join(_SRC_ROOT, ".env")
USER_ENV_FILE = os.path.join(APP_SUPPORT_DIR, ".env")

# Access token saved after the first Discogs OAuth login
OAUTH_TOKEN_FILE = os.path.join(_PROJECT_ROOT, ".oauth_tokens")

# User-agent required by the Discogs API (app name + version)
DISCOGS_USER_AGENT = "WaxTagger/2.0.1"

# Temporary folder for artwork downloads
ARTWORK_TMP_DIR = "/tmp/artwork"

# Session log files
LOG_DIR = os.path.join(_PROJECT_ROOT, "logs")


# ── .env handling ─────────────────────────────────────────────────────────────

def _read_env_file(path: str) -> dict[str, str]:
    values: dict[str, str] = {}
    if not os.path.exists(path):
        return values
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            values[k.strip()] = v
    return values


# Resolved values and where each came from: "user" | "project" | "env" | None
_values: dict[str, str] = {}
_sources: dict[str, Optional[str]] = {}


def reload() -> None:
    """Re-read every credential source and refresh the module-level constants."""
    global DISCOGS_CONSUMER_KEY, DISCOGS_CONSUMER_SECRET, SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET
    user = _read_env_file(USER_ENV_FILE)
    project = _read_env_file(PROJECT_ENV_FILE) if IS_DEV or os.path.exists(PROJECT_ENV_FILE) else {}
    for key in CREDENTIAL_KEYS:
        if user.get(key):
            _values[key], _sources[key] = user[key], "user"
        elif project.get(key):
            _values[key], _sources[key] = project[key], "project"
        elif os.environ.get(key):
            _values[key], _sources[key] = os.environ[key], "env"
        else:
            _values[key], _sources[key] = "", None
    DISCOGS_CONSUMER_KEY    = _values["DISCOGS_CONSUMER_KEY"]
    DISCOGS_CONSUMER_SECRET = _values["DISCOGS_CONSUMER_SECRET"]
    SPOTIFY_CLIENT_ID       = _values["SPOTIFY_CLIENT_ID"]
    SPOTIFY_CLIENT_SECRET   = _values["SPOTIFY_CLIENT_SECRET"]


def get_credential(key: str) -> str:
    return _values.get(key, "")


def credential_source(key: str) -> Optional[str]:
    """'user' (app settings file), 'project' (.env in checkout), 'env', or None."""
    return _sources.get(key)


def has_discogs_credentials() -> bool:
    return bool(get_credential("DISCOGS_CONSUMER_KEY") and get_credential("DISCOGS_CONSUMER_SECRET"))


def has_spotify_credentials() -> bool:
    return bool(get_credential("SPOTIFY_CLIENT_ID") and get_credential("SPOTIFY_CLIENT_SECRET"))


def save_credentials(new_values: dict[str, str]) -> None:
    """
    Write credentials to the user config file (mode 0600) and reload.
    Keys with an empty value are removed from the file, so the project .env /
    environment become effective again for them. Unknown keys in the file are kept.
    """
    os.makedirs(APP_SUPPORT_DIR, exist_ok=True)
    current = _read_env_file(USER_ENV_FILE)
    for key, value in new_values.items():
        value = (value or "").strip()
        if value:
            current[key] = value
        else:
            current.pop(key, None)
    tmp = USER_ENV_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("# WaxTagger credentials — written by the app's Settings screen.\n")
        for key, value in current.items():
            f.write(f"{key}={value}\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, USER_ENV_FILE)
    reload()


reload()
