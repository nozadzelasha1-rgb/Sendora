import uuid
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schema.organization import (
    OrganizationCreate,
    OrganizationRead,
    OrganizationUpdate,
)
from tests.seed import TEST_ROLE_ID


def _create(**overrides: object) -> OrganizationCreate:
    payload: dict[str, object] = {"name": "Acme", "type": TEST_ROLE_ID}
    payload.update(overrides)
    return OrganizationCreate.model_validate(payload)


# --- OrganizationCreate ---------------------------------------------------------


def test_create_strips_name() -> None:
    assert _create(name="  Acme  ").name == "Acme"


def test_create_empty_optional_texts_become_none() -> None:
    org = _create(contact="   ", phone="")

    assert org.contact is None
    assert org.phone is None


def test_create_strips_contact_and_phone() -> None:
    org = _create(contact="  Bob ", phone=" 555 ")

    assert org.contact == "Bob"
    assert org.phone == "555"


def test_create_optional_fields_default_to_none() -> None:
    org = _create()

    assert org.contact is None
    assert org.phone is None
    assert org.delivery_fee_gel is None


@pytest.mark.parametrize("name", ["", "   "])
def test_create_rejects_empty_name(name: str) -> None:
    with pytest.raises(ValidationError):
        _create(name=name)


def test_create_rejects_overlong_name() -> None:
    with pytest.raises(ValidationError):
        _create(name="a" * 256)


def test_create_accepts_name_at_limit() -> None:
    assert len(_create(name="a" * 255).name) == 255


def test_create_rejects_phone_over_20_chars() -> None:
    with pytest.raises(ValidationError):
        _create(phone="1" * 21)


def test_create_accepts_phone_at_20_chars() -> None:
    assert _create(phone="1" * 20).phone == "1" * 20


def test_create_rejects_negative_fee() -> None:
    with pytest.raises(ValidationError):
        _create(delivery_fee_gel="-0.01")


def test_create_rejects_three_decimal_places_fee() -> None:
    with pytest.raises(ValidationError):
        _create(delivery_fee_gel="1.234")


def test_create_accepts_two_decimal_places_fee() -> None:
    assert _create(delivery_fee_gel="12.50").delivery_fee_gel == Decimal("12.50")


def test_create_requires_name_and_type() -> None:
    with pytest.raises(ValidationError):
        OrganizationCreate.model_validate({"type": TEST_ROLE_ID})
    with pytest.raises(ValidationError):
        OrganizationCreate.model_validate({"name": "Acme"})


# --- OrganizationUpdate ---------------------------------------------------------


def test_update_rejects_empty_body() -> None:
    with pytest.raises(ValidationError):
        OrganizationUpdate.model_validate({})


@pytest.mark.parametrize("field", ["name", "type", "active"])
def test_update_rejects_null_for_non_nullable_field(field: str) -> None:
    with pytest.raises(ValidationError):
        OrganizationUpdate.model_validate({field: None})


def test_update_allows_null_for_nullable_fields() -> None:
    update = OrganizationUpdate.model_validate(
        {"contact": None, "phone": None, "delivery_fee_gel": None}
    )

    assert update.model_fields_set == {"contact", "phone", "delivery_fee_gel"}


def test_update_tracks_only_sent_fields() -> None:
    update = OrganizationUpdate.model_validate({"name": " New "})

    assert update.model_fields_set == {"name"}
    assert update.name == "New"
    assert update.model_dump(exclude_unset=True) == {"name": "New"}


def test_update_rejects_empty_name() -> None:
    with pytest.raises(ValidationError):
        OrganizationUpdate.model_validate({"name": "  "})


def test_update_rejects_invalid_fee_and_phone() -> None:
    with pytest.raises(ValidationError):
        OrganizationUpdate.model_validate({"delivery_fee_gel": "-1"})
    with pytest.raises(ValidationError):
        OrganizationUpdate.model_validate({"phone": "1" * 21})


def test_update_empty_phone_becomes_none() -> None:
    update = OrganizationUpdate.model_validate({"phone": " "})

    assert update.phone is None
    assert "phone" in update.model_fields_set


# --- OrganizationRead -----------------------------------------------------------


def test_read_from_attributes() -> None:
    class Row:
        id = uuid.uuid4()
        name = "Acme"
        type = TEST_ROLE_ID
        contact = None
        phone = None
        delivery_fee_gel = Decimal("3.00")
        active = True

    read = OrganizationRead.model_validate(Row())

    assert read.id == Row.id
    assert read.delivery_fee_gel == Decimal("3.00")
    assert read.active is True
