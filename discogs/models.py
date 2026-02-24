"""
Backwards-compat re-export. Het Release-model is verplaatst naar de root models.py
zodat het gedeeld kan worden door meerdere metadata-clients (Discogs, Spotify).
"""

from models import Release as DiscogsRelease  # noqa: F401

__all__ = ["DiscogsRelease"]
