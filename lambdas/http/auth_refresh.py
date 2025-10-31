"""Refresh Cognito tokens using a refresh token."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from lambdas.common.resp import error_response, json_response

logger = logging.getLogger(__name__)


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable {name}")
    return value


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Lambda entry point for /auth/refresh."""

    try:
        payload = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return error_response("Invalid JSON payload", status_code=400)

    refresh_token = (payload.get("refresh_token") or "").strip()
    if not refresh_token:
        return error_response("refresh_token is required", status_code=400)

    client_id = _env("USER_POOL_CLIENT_ID")

    cognito = boto3.client("cognito-idp")
    try:
        response = cognito.initiate_auth(
            ClientId=client_id,
            AuthFlow="REFRESH_TOKEN_AUTH",
            AuthParameters={
                "REFRESH_TOKEN": refresh_token,
            },
        )
    except cognito.exceptions.NotAuthorizedException:
        logger.info("Invalid refresh token")
        return error_response("Invalid refresh token", status_code=401)
    except (BotoCoreError, ClientError):
        logger.exception("Failed to refresh tokens")
        return error_response("Failed to refresh tokens", status_code=502)

    authentication = response.get("AuthenticationResult")
    if not authentication:
        logger.warning("No AuthenticationResult in refresh response")
        return error_response("Invalid refresh response", status_code=502)

    response_body = {
        "access_token": authentication.get("AccessToken"),
        "id_token": authentication.get("IdToken"),
        "expires_in": authentication.get("ExpiresIn"),
        "token_type": authentication.get("TokenType"),
    }

    response_body = {k: v for k, v in response_body.items() if v is not None}

    return json_response(response_body, status_code=200)
