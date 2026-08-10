from sqlalchemy import UniqueConstraint

from db.models.addresses import Address


def test_address_model_has_user_scoped_normalized_name_constraint():
    constraints = {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in Address.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert constraints["uq_address_user_normalized_name"] == (
        "user_id",
        "normalized_name",
    )


def test_address_model_keeps_required_and_optional_fields_distinct():
    columns = Address.__table__.columns
    assert columns.name.nullable is False
    assert columns.city.nullable is False
    assert columns.street.nullable is False
    assert columns.house.nullable is False
    assert columns.postal_code.nullable is True
    assert columns.delivery_comment.nullable is True
