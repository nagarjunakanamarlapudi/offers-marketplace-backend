"""Start custom authentication by issuing an OTP challenge."""

from __future__ import annotations

import json
import logging
import os
import secrets
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from lambdas.common.phone import (
    normalize,
    validate_e164,
)
from lambdas.common.resp import (
    error_response,
    json_response,
)

logger = logging.getLogger(__name__)


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable {name}")
    return value


def _ensure_user(
    client: boto3.client, user_pool_id: str, client_id: str, phone: str
) -> None:
    """Ensure a Cognito user exists for the supplied phone number."""

    try:
        user = client.admin_get_user(UserPoolId=user_pool_id, Username=phone)
    except client.exceptions.UserNotFoundException:
        password = secrets.token_urlsafe(24)
        try:
            client.sign_up(
                ClientId=client_id,
                Username=phone,
                Password=password,
                UserAttributes=[{"Name": "phone_number", "Value": phone}],
            )
        except client.exceptions.UsernameExistsException:
            logger.debug("Username already exists during sign-up: %s", phone)

        client.admin_confirm_sign_up(UserPoolId=user_pool_id, Username=phone)
        client.admin_update_user_attributes(
            UserPoolId=user_pool_id,
            Username=phone,
            UserAttributes=[
                {"Name": "phone_number", "Value": phone},
                {"Name": "phone_number_verified", "Value": "true"},
            ],
        )
        logger.info("Created Cognito user for %s", phone)
        return
    except (BotoCoreError, ClientError):
        logger.exception("Failed to look up Cognito user for %s", phone)
        raise

    attributes = {attr["Name"]: attr["Value"] for attr in user.get("UserAttributes", [])}
    updates = []
    if attributes.get("phone_number") != phone:
        updates.append({"Name": "phone_number", "Value": phone})
    if attributes.get("phone_number_verified") != "true":
        updates.append({"Name": "phone_number_verified", "Value": "true"})
    if updates:
        client.admin_update_user_attributes(
            UserPoolId=user_pool_id, Username=phone, UserAttributes=updates
        )

    status = user.get("UserStatus")
    if status == "UNCONFIRMED":
        client.admin_confirm_sign_up(UserPoolId=user_pool_id, Username=phone)


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Lambda entry point for /auth/start."""

    try:
        payload = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return error_response("Invalid JSON payload", status_code=400)

    phone = normalize(payload.get("phone"))
    if not phone:
        return error_response("phone is required", status_code=400)
    if not validate_e164(phone):
        return error_response("phone must be in E.164 format", status_code=400)

    user_pool_id = _env("USER_POOL_ID")
    client_id = _env("USER_POOL_CLIENT_ID")
    dev_echo = os.environ.get("SMS_DEV_ECHO", "").lower() == "true"

    cognito = boto3.client("cognito-idp")

    try:
        _ensure_user(cognito, user_pool_id, client_id, phone)

        auth_response = cognito.admin_initiate_auth(
            UserPoolId=user_pool_id,
            ClientId=client_id,
            AuthFlow="CUSTOM_AUTH",
            AuthParameters={
                "USERNAME": phone,
            },
        )
    except cognito.exceptions.InvalidParameterException as exc:
        logger.exception("Cognito rejected auth start for %s", phone)
        return error_response(str(exc), status_code=400)
    except (BotoCoreError, ClientError):
        logger.exception("Failed to start custom auth for %s", phone)
        return error_response("Failed to start authentication", status_code=502)

    challenge_name = auth_response.get("ChallengeName")
    session = auth_response.get("Session")
    challenge_params = auth_response.get("ChallengeParameters") or {}

    if challenge_name != "CUSTOM_CHALLENGE" or not session:
        logger.error(
            "Unexpected Cognito response: challenge=%s session=%s",
            challenge_name,
            bool(session),
        )
        return error_response("Unexpected authentication response", status_code=502)

    response_body: dict[str, Any] = {
        "session": session,
        "phone": phone,
    }
    if dev_echo:
        dev_otp = challenge_params.get("dev_otp")
        if dev_otp:
            response_body["dev_otp"] = dev_otp

    return json_response(response_body, status_code=200)
