from __future__ import annotations

import argparse
import sys
from urllib.parse import urljoin

import httpx


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke test for the Offers API")
    parser.add_argument(
        "--api-url",
        required=True,
        help="Base URL of the deployed API Gateway endpoint",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    health_url = urljoin(args.api_url.rstrip("/") + "/", "health")

    response = httpx.get(health_url, timeout=10)
    response.raise_for_status()

    payload = response.json()
    status = payload.get("status")
    version = payload.get("version")

    if status != "ok":
        msg = f"Unexpected status returned from {health_url}: {payload}"
        raise AssertionError(msg)

    print(f"Smoke test succeeded against {health_url} (version={version})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
