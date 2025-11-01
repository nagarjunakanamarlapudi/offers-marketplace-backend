from __future__ import annotations

import os
import logging

import boto3
from botocore.exceptions import BotoCoreError, ClientError

import aws_cdk as cdk

from infra.api_stack import ApiStack


def _parse_allowed_origins(raw):
    if not raw:
        return None
    if isinstance(raw, str):
        if raw.strip() == "*":
            return ["*"]
        return [segment.strip() for segment in raw.split(",") if segment.strip()]
    if isinstance(raw, list):
        return raw
    raise ValueError("allowed_origins context must be a string or list")


def _resolve_env() -> cdk.Environment | None:
    region = (
        os.environ.get("AWS_REGION")
        or os.environ.get("CDK_DEFAULT_REGION")
        or os.environ.get("AWS_DEFAULT_REGION")
    )

    account = os.environ.get("AWS_ACCOUNT_ID") or os.environ.get("CDK_DEFAULT_ACCOUNT")

    if not account:
        try:
            session = boto3.session.Session(region_name=region)
            account = session.client("sts").get_caller_identity()["Account"]
            region = region or session.region_name
        except (BotoCoreError, ClientError):
            # Could not resolve account via STS (likely missing credentials).
            # Leave account unset and allow CDK to run in environment-agnostic mode,
            # but surface a helpful message for local developers.
            account = None
            logging.getLogger(__name__).warning(
                "Unable to resolve AWS account via STS - no credentials found. "
                "Set AWS_PROFILE or AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY to allow CDK to deploy."
            )

    if account and region:
        return cdk.Environment(account=account, region=region)
    return None


app = cdk.App()

stage = (
    app.node.try_get_context("stage")
    or os.environ.get("STACK_STAGE")
    or "dev"
)
cdk_env = _resolve_env()
allowed_origins = _parse_allowed_origins(app.node.try_get_context("allowed_origins"))
google_client_id = (
    app.node.try_get_context("google_client_id")
    or os.environ.get("GOOGLE_CLIENT_ID")
)
if not google_client_id:
    raise ValueError(
        "Google client id must be provided via CDK context 'google_client_id' "
        "or GOOGLE_CLIENT_ID environment variable."
    )

ApiStack(
    app,
    f"OffersApiStack-{stage}",
    stage=stage,
    google_client_id=google_client_id,
    allowed_origins=allowed_origins,
    env=cdk_env,
)

app.synth()
