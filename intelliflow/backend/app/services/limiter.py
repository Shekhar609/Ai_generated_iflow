"""Shared slowapi limiter instance.

TODO: when auth lands, swap `get_remote_address` for a user-id key function.
"""
from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

from ..config import get_settings

_settings = get_settings()

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[f"{_settings.rate_limit_other_per_minute}/minute"],
)
