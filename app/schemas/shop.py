from datetime import datetime
from decimal import Decimal
import uuid
from pydantic import BaseModel, ConfigDict, Field


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    name: str
    is_active: bool
    created_at: datetime


class OrderItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_name: str
    sku: str
    quantity: int
    price: Decimal


class OrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    status: str
    total_amount: Decimal
    currency: str
    shipping_address: str | None
    created_at: datetime
    updated_at: datetime
    items: list[OrderItemRead] = Field(default_factory=list)


class DropRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    status: str
    total_inventory: int
    start_time: datetime
    end_time: datetime


class DropEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    drop_id: uuid.UUID
    status: str
    position: int | None
    created_at: datetime
    drop: DropRead | None = None


class RefundRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    order_id: uuid.UUID
    amount: Decimal
    reason: str
    status: str
    idempotency_key: str
    created_at: datetime
    processed_at: datetime | None
