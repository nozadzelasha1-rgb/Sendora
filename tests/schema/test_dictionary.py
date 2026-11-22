import pytest
from pydantic import ValidationError

from app.schema.dictionary import DictionaryItemCreate, DictionaryItemUpdate


def test_create_strips_name_and_description() -> None:
    item = DictionaryItemCreate(name="  Courier  ", description="  Fast  ")

    assert item.name == "Courier"
    assert item.description == "Fast"


def test_create_blank_description_becomes_none() -> None:
    assert DictionaryItemCreate(name="Courier", description="   ").description is None


@pytest.mark.parametrize("name", ["", "   "])
def test_create_rejects_blank_name(name: str) -> None:
    with pytest.raises(ValidationError):
        DictionaryItemCreate(name=name)


def test_create_rejects_overlong_name() -> None:
    with pytest.raises(ValidationError):
        DictionaryItemCreate(name="a" * 256)


def test_create_accepts_name_at_limit() -> None:
    assert len(DictionaryItemCreate(name="a" * 255).name) == 255


def test_create_rejects_overlong_description() -> None:
    with pytest.raises(ValidationError):
        DictionaryItemCreate(name="Courier", description="d" * 1001)


def test_update_rejects_empty_body() -> None:
    with pytest.raises(ValidationError):
        DictionaryItemUpdate.model_validate({})


def test_update_rejects_null_name() -> None:
    with pytest.raises(ValidationError):
        DictionaryItemUpdate.model_validate({"name": None})


def test_update_allows_clearing_description() -> None:
    update = DictionaryItemUpdate.model_validate({"description": None})

    assert update.description is None
    assert update.model_fields_set == {"description"}


def test_update_tracks_only_sent_fields() -> None:
    update = DictionaryItemUpdate.model_validate({"name": " New "})

    assert update.model_dump(exclude_unset=True) == {"name": "New"}
