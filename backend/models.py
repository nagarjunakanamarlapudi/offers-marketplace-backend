"""Pydantic models for the offers backend."""

from decimal import Decimal

from pydantic import BaseModel, Field, field_serializer


class ItemBase(BaseModel):
    item_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1, max_length=255)
    price: Decimal = Field(..., gt=0)


class ItemCreate(ItemBase):
    """Model used when creating or updating an item."""


class Item(ItemBase):
    """Model returned to clients."""

    @field_serializer("price")
    def _serialize_price(self, value: Decimal) -> float:
        return float(value)
