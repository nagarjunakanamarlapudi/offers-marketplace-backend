"""HTTP response helpers for Lambda proxy integrations."""

from __future__ import annotations

import json
from typing import Any, Mapping

_DEFAULT_HEADERS = {
    "Content-Type": "application/json",
}


def json_response(
    payload: Mapping[str, Any] | None,
    *,
    status_code: int = 200,
    headers: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Return a JSON response compatible with API Gateway Lambda proxy."""

    body = "" if payload is None else json.dumps(payload)

    merged_headers = dict(_DEFAULT_HEADERS)
    if headers:
        merged_headers.update(headers)

    return {
        "statusCode": status_code,
        "headers": merged_headers,
        "body": body,
    }


def error_response(message: str, *, status_code: int = 400) -> dict[str, Any]:
    """Return a standardized error response."""

    return json_response({"error": message}, status_code=status_code)

