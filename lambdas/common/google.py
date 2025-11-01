"""Google authentication helpers."""

from __future__ import annotations

import logging
from typing import Any

from google.auth.transport import requests
from google.oauth2 import id_token as google_id_token

logger = logging.getLogger(__name__)

GOOGLE_CHALLENGE_ANSWER = "GOOGLE_LOGIN_OK"

_REQUEST = requests.Request()


class GoogleTokenError(ValueError):
    """Raised when a Google ID token cannot be validated."""


def verify_id_token(token: str, audience: str) -> dict[str, Any]:
    """Verify a Google ID token and return the decoded claims."""

    if not token:
        raise GoogleTokenError("Missing token")
    if not audience:
        raise GoogleTokenError("Missing audience")

    try:
        claims = google_id_token.verify_oauth2_token(token, _REQUEST, audience)
    except ValueError as exc:  # google-auth raises ValueError for verification failures
        logger.info("Failed to verify Google ID token: %s", exc)
        raise GoogleTokenError(str(exc)) from exc

    issuer = claims.get("iss")
    if issuer not in {"accounts.google.com", "https://accounts.google.com"}:
        raise GoogleTokenError("Invalid token issuer")

    return claims
