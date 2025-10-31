"""FastAPI application providing CRUD operations for items."""

from __future__ import annotations

import asyncio
import logging
import os
from decimal import Decimal
from functools import lru_cache

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum

from backend import __version__
from backend.models import Item, ItemCreate

logger = logging.getLogger(__name__)


def _parse_allowed_origins(raw_origins: str | None) -> list[str]:
    if not raw_origins:
        return ["*"]
    if raw_origins.strip() == "*":
        return ["*"]
    return [origin.strip() for origin in raw_origins.split(",") if origin.strip()]


def _decimal_to_float(payload: dict) -> dict:
    """Recursively convert Decimal values to float for JSON serialization."""

    def convert(value):
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, dict):
            return {k: convert(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [convert(v) for v in value]
        return value

    return convert(payload)


def _extract_jwt_claims(request: Request) -> dict:
    """Return JWT claims made available by API Gateway's HttpJwtAuthorizer."""

    try:
        return (
            request.scope.get("aws.event", {})
            .get("requestContext", {})
            .get("authorizer", {})
            .get("jwt", {})
            .get("claims", {})
        )
    except AttributeError:
        return {}


@lru_cache(maxsize=1)
def get_dynamodb_table():
    table_name = os.environ.get("ITEMS_TABLE_NAME")
    if not table_name:
        raise RuntimeError("ITEMS_TABLE_NAME environment variable must be set")

    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    session_kwargs = {"region_name": region} if region else {}
    session = boto3.session.Session(**session_kwargs)

    endpoint_url = os.environ.get("DYNAMODB_ENDPOINT_URL") or os.environ.get(
        "AWS_ENDPOINT_URL"
    )
    resource = session.resource("dynamodb", endpoint_url=endpoint_url)
    return resource.Table(table_name)


def app_factory() -> FastAPI:
    app = FastAPI(title="Offers API", version=__version__)

    parsed_origins = _parse_allowed_origins(os.environ.get("ALLOWED_ORIGINS"))

    app.add_middleware(
        CORSMiddleware,
        allow_origins=parsed_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials="*" not in parsed_origins,
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.post("/items", status_code=status.HTTP_201_CREATED, response_model=Item)
    async def create_item(item: ItemCreate, request: Request) -> Item:
        table = get_dynamodb_table()
        payload = item.model_dump()
        claims = _extract_jwt_claims(request)
        sub = claims.get("sub")
        if sub:
            logger.debug("create_item requested by user %s", sub)

        def _execute_put():
            table.put_item(Item=payload)

        try:
            await asyncio.to_thread(_execute_put)
        except (BotoCoreError, ClientError) as exc:
            logger.exception("Failed to store item %s", item.item_id)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to store item",
            ) from exc

        return Item.model_validate(payload)

    @app.get("/items/{item_id}", response_model=Item)
    async def get_item(item_id: str, request: Request) -> Item:
        table = get_dynamodb_table()
        claims = _extract_jwt_claims(request)
        sub = claims.get("sub")
        if sub:
            logger.debug("get_item requested by user %s", sub)

        def _execute_get():
            return table.get_item(Key={"item_id": item_id})

        try:
            response = await asyncio.to_thread(_execute_get)
        except (BotoCoreError, ClientError) as exc:
            logger.exception("Failed to fetch item %s", item_id)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to fetch item",
            ) from exc

        item = response.get("Item")
        if not item:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Item {item_id} not found",
            )

        return Item.model_validate(_decimal_to_float(item))

    return app


app = app_factory()
handler = Mangum(app)
