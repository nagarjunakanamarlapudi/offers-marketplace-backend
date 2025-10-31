"""VerifyAuthChallengeResponse Lambda trigger."""

from __future__ import annotations

import hmac
import json
import logging
import time
from typing import Any


logger = logging.getLogger(__name__)


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
    """Entry point for the Cognito VerifyAuthChallengeResponse trigger."""

    now = int(time.time())

    response = event.setdefault("response", {})
    response["answerCorrect"] = False

    request = event.get("request", {})
    private_params = request.get("privateChallengeParameters") or {}
    metadata = _parse_metadata(request.get("challengeMetadata"))
    expected_answer = private_params.get("answer")
    exp_value = private_params.get("exp") or metadata.get("exp")

    if expected_answer is None:
        logger.warning("Missing expected OTP in private parameters")
        return event

    if exp_value:
        try:
            expires_at = int(exp_value)
        except (TypeError, ValueError):
            expires_at = None
        if expires_at and now > expires_at:
            logger.info("OTP expired at %s (now=%s)", expires_at, now)
            return event

    provided_answer = request.get("challengeAnswer")
    if provided_answer is None:
        logger.info("No OTP provided by client")
        return event

    if hmac.compare_digest(str(expected_answer), str(provided_answer)):
        response["answerCorrect"] = True

    return event
