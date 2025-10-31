"""Utilities for validating and normalizing phone numbers."""

from __future__ import annotations

import re

E164_PATTERN = re.compile(r"^\+[1-9]\d{6,14}$")


def normalize(phone: str | None) -> str | None:
    """Trim whitespace from an input phone number."""

    if phone is None:
        return None
    return phone.strip()


def validate_e164(phone: str) -> bool:
    """Return True if the supplied phone number matches the E.164 format."""

    return bool(E164_PATTERN.fullmatch(phone))

