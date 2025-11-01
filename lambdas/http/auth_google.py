"""Authenticate users via Google Sign-In and return Cognito tokens."""

from __future__ import annotations

import json
import logging
import os
import secrets
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from lambdas.common.google import (
    GOOGLE_CHALLENGE_ANSWER,
    GoogleTokenError,
    verify_id_token,
)
from lambdas.common.resp import error_response, json_response

logger = logging.getLogger(__name__)


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable {name}")
    return value


def _normalize_attributes(claims: dict[str, Any]) -> list[dict[str, str]]:
    """Convert Google claims to Cognito user attributes."""

    attrs: list[dict[str, str]] = []

    email = claims.get("email")
    if email:
        attrs.append({"Name": "email", "Value": email})

    email_verified = claims.get("email_verified")
    if email_verified is not None:
        attrs.append({"Name": "email_verified", "Value": "true" if email_verified else "false"})

    name = claims.get("name")
    if name:
        attrs.append({"Name": "name", "Value": name})

    given_name = claims.get("given_name")
    if given_name:
        attrs.append({"Name": "given_name", "Value": given_name})

    family_name = claims.get("family_name")
    if family_name:
        attrs.append({"Name": "family_name", "Value": family_name})

    picture = claims.get("picture")
    if picture:
        attrs.append({"Name": "picture", "Value": picture})

    return attrs


def _ensure_google_user(
    client: Any,
    user_pool_id: str,
    client_id: str,
    username: str,
    attributes: list[dict[str, str]],
) -> None:
    """Ensure a Cognito user exists for the given Google identity."""

    try:
        user = client.admin_get_user(UserPoolId=user_pool_id, Username=username)
    except client.exceptions.UserNotFoundException:
        password = secrets.token_urlsafe(24)
        try:
            client.sign_up(
                ClientId=client_id,
                Username=username,
                Password=password,
                UserAttributes=attributes,
            )
        except client.exceptions.UsernameExistsException:
            logger.debug("Username already exists during sign-up: %s", username)

        client.admin_confirm_sign_up(UserPoolId=user_pool_id, Username=username)
        if attributes:
            client.admin_update_user_attributes(
                UserPoolId=user_pool_id,
                Username=username,
                UserAttributes=attributes,
            )
        logger.info("Created Cognito user for Google identity %s", username)
        return
    except (BotoCoreError, ClientError):
        logger.exception("Failed to look up Cognito user for %s", username)
        raise

    attributes_by_name = {attr["Name"]: attr["Value"] for attr in user.get("UserAttributes", [])}
    updates = []
    for attr in attributes:
        if attributes_by_name.get(attr["Name"]) != attr["Value"]:
            updates.append(attr)

    if updates:
        client.admin_update_user_attributes(
            UserPoolId=user_pool_id,
            Username=username,
            UserAttributes=updates,
        )

    status = user.get("UserStatus")
    if status == "UNCONFIRMED":
        client.admin_confirm_sign_up(UserPoolId=user_pool_id, Username=username)


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Lambda entry point for /auth/google."""

    try:
        payload = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return error_response("Invalid JSON payload", status_code=400)

    id_token = (payload.get("id_token") or "").strip()
    if not id_token:
        return error_response("id_token is required", status_code=400)

    google_client_id = _env("GOOGLE_CLIENT_ID")
    user_pool_id = _env("USER_POOL_ID")
    client_id = _env("USER_POOL_CLIENT_ID")

    try:
        claims = verify_id_token(id_token, google_client_id)
    except GoogleTokenError as exc:
        logger.info("Invalid Google token: %s", exc)
        return error_response("Invalid Google ID token", status_code=401)

    sub = claims.get("sub")
    email = claims.get("email")
    if not sub:
        logger.info("Google token missing subject claim")
        return error_response("Invalid Google ID token", status_code=401)
    if not email:
        logger.info("Google token missing email claim")
        return error_response("Google account email is required", status_code=400)

    username = f"google:{sub}"
    attributes = _normalize_attributes(claims)

    cognito = boto3.client("cognito-idp")

    try:
        _ensure_google_user(cognito, user_pool_id, client_id, username, attributes)
    except cognito.exceptions.InvalidParameterException as exc:
        logger.exception("Cognito rejected Google user %s", username)
        return error_response(str(exc), status_code=400)
    except (BotoCoreError, ClientError):
        logger.exception("Failed to ensure Cognito user for %s", username)
        return error_response("Failed to start authentication", status_code=502)

    try:
        auth_response = cognito.admin_initiate_auth(
            UserPoolId=user_pool_id,
            ClientId=client_id,
            AuthFlow="CUSTOM_AUTH",
            AuthParameters={
                "USERNAME": username,
            },
            ClientMetadata={
                "login_provider": "google",
                "google_sub": sub,
            },
        )
    except cognito.exceptions.InvalidParameterException as exc:
        logger.exception("Cognito rejected auth start for %s", username)
        return error_response(str(exc), status_code=400)
    except (BotoCoreError, ClientError):
        logger.exception("Failed to start Google custom auth for %s", username)
        return error_response("Failed to start authentication", status_code=502)

    challenge_name = auth_response.get("ChallengeName")
    session = auth_response.get("Session")

    if challenge_name != "CUSTOM_CHALLENGE" or not session:
        logger.error(
            "Unexpected Cognito response for Google login: challenge=%s session=%s",
            challenge_name,
            bool(session),
        )
        return error_response("Unexpected authentication response", status_code=502)

    try:
        challenge_response = cognito.admin_respond_to_auth_challenge(
            UserPoolId=user_pool_id,
            ClientId=client_id,
            ChallengeName="CUSTOM_CHALLENGE",
            ChallengeResponses={
                "USERNAME": username,
                "ANSWER": GOOGLE_CHALLENGE_ANSWER,
            },
            Session=session,
        )
    except (BotoCoreError, ClientError):
        logger.exception("Failed to complete Google custom auth for %s", username)
        return error_response("Failed to verify authentication", status_code=502)

    authentication = challenge_response.get("AuthenticationResult")
    if not authentication:
        challenge = challenge_response.get("ChallengeName")
        logger.warning(
            "No authentication result returned for Google login; challenge=%s user=%s",
            challenge,
            username,
        )
        return error_response("Invalid authentication response", status_code=401)

    response_body = {
        "access_token": authentication.get("AccessToken"),
        "id_token": authentication.get("IdToken"),
        "refresh_token": authentication.get("RefreshToken"),
        "expires_in": authentication.get("ExpiresIn"),
        "token_type": authentication.get("TokenType"),
    }
    response_body = {k: v for k, v in response_body.items() if v is not None}

    return json_response(response_body, status_code=200)
