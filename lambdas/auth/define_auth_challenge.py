"""DefineAuthChallenge Lambda trigger."""

from __future__ import annotations

import json
import os
import time
from typing import Any

DEFAULT_MAX_ATTEMPTS = 5


def _load_int(env_key: str, fallback: int) -> int:
    try:
        return int(os.environ.get(env_key, fallback))
    except (TypeError, ValueError):
        return fallback


def _parse_metadata(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        return {}
    return {}


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Entry point for the Cognito DefineAuthChallenge trigger."""

    max_attempts = _load_int("OTP_MAX_ATTEMPTS", DEFAULT_MAX_ATTEMPTS)
    response = event.setdefault("response", {})
    response.update(
        {
            "issueTokens": False,
            "failAuthentication": False,
        }
    )

    session = event.get("request", {}).get("session", [])
    if not session:
        response["challengeName"] = "CUSTOM_CHALLENGE"
        return event

    last_attempt = session[-1]
    metadata = _parse_metadata(last_attempt.get("challengeMetadata"))
    now = int(time.time())
    expires_at = metadata.get("exp")
    attempt_number = metadata.get("attempt") or len(session)

    if last_attempt.get("challengeResult"):
        response["issueTokens"] = True
        return event

    if attempt_number >= max_attempts:
        response["failAuthentication"] = True
        return event

    if expires_at and now > int(expires_at):
        response["failAuthentication"] = True
        return event

    response["challengeName"] = "CUSTOM_CHALLENGE"
    return event

