"""Verify OTP challenge and return Cognito tokens."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from lambdas.common.phone import normalize, validate_e164
from lambdas.common.resp import error_response, json_response

logger = logging.getLogger(__name__)


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable {name}")
    return value


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Lambda entry point for /auth/verify."""

    try:
        payload = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return error_response("Invalid JSON payload", status_code=400)

    phone = normalize(payload.get("phone"))
    otp = (payload.get("otp") or "").strip()
    session = payload.get("session")

    if not phone or not validate_e164(phone):
        return error_response("phone must be in E.164 format", status_code=400)
    if not otp or not otp.isdigit() or len(otp) != 6:
        return error_response("otp must be a 6-digit code", status_code=400)
    if not session:
        return error_response("session is required", status_code=400)

    user_pool_id = _env("USER_POOL_ID")
    client_id = _env("USER_POOL_CLIENT_ID")

    cognito = boto3.client("cognito-idp")

    try:
        challenge_response = cognito.admin_respond_to_auth_challenge(
            UserPoolId=user_pool_id,
            ClientId=client_id,
            ChallengeName="CUSTOM_CHALLENGE",
            ChallengeResponses={
                "USERNAME": phone,
                "ANSWER": otp,
            },
            Session=session,
        )
    except cognito.exceptions.NotAuthorizedException:
        logger.info("Invalid OTP for %s", phone)
        return error_response("Invalid OTP or session expired", status_code=401)
    except cognito.exceptions.ExpiredCodeException:
        logger.info("Expired OTP for %s", phone)
        return error_response("OTP expired", status_code=401)
    except cognito.exceptions.CodeMismatchException:
        logger.info("Incorrect OTP for %s", phone)
        return error_response("Invalid OTP", status_code=401)
    except (BotoCoreError, ClientError):
        logger.exception("Failed to verify custom auth for %s", phone)
        return error_response("Failed to verify authentication", status_code=502)

    authentication = challenge_response.get("AuthenticationResult")
    if not authentication:
        challenge_name = challenge_response.get("ChallengeName")
        logger.warning(
            "No authentication result; challenge=%s user=%s", challenge_name, phone
        )
        return error_response("Invalid authentication response", status_code=401)

    response_body = {
        "access_token": authentication.get("AccessToken"),
        "id_token": authentication.get("IdToken"),
        "refresh_token": authentication.get("RefreshToken"),
        "expires_in": authentication.get("ExpiresIn"),
        "token_type": authentication.get("TokenType"),
    }

    # Remove None entries (e.g., refresh token may be omitted on certain flows).
    response_body = {k: v for k, v in response_body.items() if v is not None}

    return json_response(response_body, status_code=200)
