"""CreateAuthChallenge Lambda trigger."""

from __future__ import annotations

import json
import logging
import os
import secrets
import time
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from lambdas.common.phone import normalize

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

DEFAULT_TTL_SECONDS = 300


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


def _generate_otp(length: int = 6) -> str:
    upper = 10**length
    return f"{secrets.randbelow(upper):0{length}d}"


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Entry point for the Cognito CreateAuthChallenge trigger."""

    logger.info(f"CreateAuthChallenge event: {event}")
    ttl_seconds = _load_int("OTP_TTL_SECONDS", DEFAULT_TTL_SECONDS)
    dev_echo = os.environ.get("SMS_DEV_ECHO", "").lower() == "true"

    session = event.get("request", {}).get("session", [])
    last_metadata = _parse_metadata(session[-1].get("challengeMetadata")) if session else {}
    attempt_number = int(last_metadata.get("attempt", 0)) + 1

    otp = _generate_otp()
    expires_at = int(time.time()) + ttl_seconds

    private_params = {
        "answer": otp,
        "exp": str(expires_at),
        "attempt": str(attempt_number),
    }

    event.setdefault("response", {})
    event["response"]["privateChallengeParameters"] = private_params
    event["response"]["challengeMetadata"] = json.dumps(
        {
            "exp": expires_at,
            "attempt": attempt_number,
        }
    )

    public_params = {
        "deliveryMedium": "SMS",
    }
    if dev_echo:
        public_params["dev_otp"] = otp
    event["response"]["publicChallengeParameters"] = public_params

    phone_number = normalize(
        event.get("request", {}).get("userAttributes", {}).get("phone_number")
    )
    if not phone_number:
        logger.error("Phone number missing on user attributes; cannot deliver OTP")
        raise RuntimeError("Phone number missing for user")

    message = f"Your Offers login code is {otp}"

    sns_client = boto3.client("sns")
    try:
        sns_client.publish(
            PhoneNumber=phone_number, 
            Message=message,
            MessageAttributes={
                "AWS.SNS.SMS.SMSType": {
                    "DataType": "String",
                    "StringValue": "Transactional",
                },
            }
        )
        logger.info("Sent OTP via SNS to %s", phone_number)
        logger.info("message %s : ", message)
    except (BotoCoreError, ClientError):
        logger.exception("Failed to send OTP via SNS to %s", phone_number)
        raise

    if dev_echo:
        logger.info("OTP issued for %s (dev echo enabled)", phone_number)
    else:
        logger.info("OTP issued for %s", phone_number)

    return event
