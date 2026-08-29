"""
Backwards-compat re-export. Het Release-model is in waxtagger.models.
"""

from waxtagger.models import Release as DiscogsRelease  # noqa: F401

__all__ = ["DiscogsRelease"]
