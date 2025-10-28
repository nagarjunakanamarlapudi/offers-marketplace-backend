from __future__ import annotations

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


app = cdk.App()
allowed_origins = _parse_allowed_origins(app.node.try_get_context("allowed_origins"))

ApiStack(
    app,
    "OffersApiStack",
    allowed_origins=allowed_origins,
)

app.synth()
