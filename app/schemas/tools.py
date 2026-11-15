from decimal import Decimal
from typing import Any
import uuid
from pydantic import BaseModel, ConfigDict, Field


class GetOrderInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order_id: uuid.UUID = Field(
        ...,
        description="The unique UUID of the order to look up.",
    )


class ListUserOrdersInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Maximum number of recent orders to return (1-50).",
    )


class GetDropEntryStatusInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    drop_id: uuid.UUID = Field(
        ...,
        description="The unique UUID of the sneaker drop.",
    )


class IssueRefundInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order_id: uuid.UUID = Field(
        ...,
        description="The unique UUID of the order to refund.",
    )
    amount: Decimal = Field(
        ...,
        gt=0,
        description="The monetary amount to refund (must be strictly greater than 0).",
    )
    reason: str = Field(
        ...,
        min_length=3,
        description="The validated reason for issuing the refund.",
    )
    idempotency_key: str = Field(
        ...,
        min_length=8,
        description="Unique UUID or token to guarantee idempotency and prevent double-refunds.",
    )


class CancelOrderInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order_id: uuid.UUID = Field(
        ...,
        description="The unique UUID of the order to cancel.",
    )
    reason: str = Field(
        ...,
        min_length=3,
        description="The customer or operational reason for order cancellation.",
    )
    idempotency_key: str = Field(
        ...,
        min_length=8,
        description="Unique UUID or token to guarantee idempotency and prevent duplicate cancellations.",
    )


class ToolResponse(BaseModel):
    success: bool
    data: Any | None = None
    error: str | None = None
