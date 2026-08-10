import pytest
from pydantic import ValidationError

from db.schemas.addresses import AddressCreate, AddressUpdate


def valid_address():
    return {
        "name": "  Дом  ",
        "city": "  Калининград ",
        "street": " Ленинский проспект ",
        "house": " 10 ",
        "postal_code": "236000",
    }


def test_create_trims_fields_and_accepts_six_digit_postal_code():
    address = AddressCreate(**valid_address())
    assert address.name == "Дом"
    assert address.city == "Калининград"
    assert address.postal_code == "236000"


@pytest.mark.parametrize("postal_code", ["23600", "2360000", "23A000"])
def test_create_rejects_invalid_postal_code(postal_code):
    with pytest.raises(ValidationError):
        AddressCreate(**{**valid_address(), "postal_code": postal_code})


def test_update_requires_at_least_one_field_and_rejects_null_required_fields():
    with pytest.raises(ValidationError):
        AddressUpdate()
    with pytest.raises(ValidationError):
        AddressUpdate(name=None)
    assert AddressUpdate(apartment=None).model_fields_set == {"apartment"}
