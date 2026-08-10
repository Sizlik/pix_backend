from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    StringConstraints,
    field_validator,
    model_validator,
)

AddressName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
]
City = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
]
Street = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]
ShortPart = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=30),
]
PostalCode = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^\d{6}$"),
]
DeliveryCommentValue = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
]


class AddressFields(BaseModel):
    name: AddressName
    city: City
    street: Street
    house: ShortPart
    postal_code: PostalCode | None = None
    building: ShortPart | None = None
    apartment: ShortPart | None = None
    delivery_comment: DeliveryCommentValue | None = None

    @field_validator(
        "postal_code",
        "building",
        "apartment",
        "delivery_comment",
        mode="before",
    )
    @classmethod
    def blank_optional_string_is_none(cls, value):
        return None if isinstance(value, str) and not value.strip() else value


class AddressCreate(AddressFields):
    pass


class AddressUpdate(BaseModel):
    name: AddressName | None = None
    city: City | None = None
    street: Street | None = None
    house: ShortPart | None = None
    postal_code: PostalCode | None = None
    building: ShortPart | None = None
    apartment: ShortPart | None = None
    delivery_comment: DeliveryCommentValue | None = None

    @field_validator(
        "postal_code",
        "building",
        "apartment",
        "delivery_comment",
        mode="before",
    )
    @classmethod
    def blank_optional_string_is_none(cls, value):
        return None if isinstance(value, str) and not value.strip() else value

    @model_validator(mode="after")
    def require_nonempty_patch(self):
        if not self.model_fields_set:
            raise ValueError("at least one field must be provided")
        required = {"name", "city", "street", "house"}
        if any(
            field in self.model_fields_set and getattr(self, field) is None
            for field in required
        ):
            raise ValueError("required address fields cannot be null")
        return self


class AddressRead(AddressFields):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    is_default: bool
    created_at: datetime
    updated_at: datetime
    last_used_at: datetime | None


class AddressListResponse(BaseModel):
    items: list[AddressRead]
    total: int
    limit: int
    offset: int
