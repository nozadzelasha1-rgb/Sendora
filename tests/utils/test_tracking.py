import re

from app.utils.tracking import (
    TRACKING_PREFIX,
    compute_check_char,
    generate_tracking_number,
    is_valid_tracking_number,
    normalize_tracking_number,
)

_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
_FORMAT = re.compile(rf"SND-[{_ALPHABET}]{{4}}-[{_ALPHABET}]{{4}}-[{_ALPHABET}]")


def _flip(char: str) -> str:
    return "3" if char != "3" else "4"


def test_generated_number_has_expected_format() -> None:
    number = generate_tracking_number()
    assert _FORMAT.fullmatch(number)
    assert number.startswith(TRACKING_PREFIX)
    assert len(number) == 15


def test_generated_numbers_are_valid() -> None:
    for _ in range(200):
        assert is_valid_tracking_number(generate_tracking_number())


def test_generated_numbers_are_unique() -> None:
    numbers = {generate_tracking_number() for _ in range(1_000)}
    assert len(numbers) == 1_000


def test_check_char_is_from_alphabet() -> None:
    check = compute_check_char("ABCDEFGH")
    assert check in _ALPHABET


def test_check_char_is_deterministic() -> None:
    assert compute_check_char("7K4M9XQ2") == compute_check_char("7K4M9XQ2")


def test_lowercase_and_unhyphenated_input_is_accepted() -> None:
    number = generate_tracking_number()
    assert is_valid_tracking_number(number.lower())
    assert is_valid_tracking_number(number.replace("-", ""))
    assert is_valid_tracking_number(number.replace("-", " "))


def test_normalize_removes_hyphens_whitespace_and_case() -> None:
    assert normalize_tracking_number(" snd-7k4m 9xq2-h ") == "SND7K4M9XQ2H"


def test_single_char_typo_in_body_is_rejected() -> None:
    number = normalize_tracking_number(generate_tracking_number())
    prefix_length = len(TRACKING_PREFIX)
    for index in range(prefix_length, len(number) - 1):
        typo = number[:index] + _flip(number[index]) + number[index + 1 :]
        assert not is_valid_tracking_number(typo)


def test_adjacent_swap_in_body_is_rejected() -> None:
    body = "7K4M9XQ2"
    valid = TRACKING_PREFIX + body + compute_check_char(body)
    assert is_valid_tracking_number(valid)
    start = len(TRACKING_PREFIX)
    chars = list(valid)
    chars[start], chars[start + 1] = chars[start + 1], chars[start]
    swapped = "".join(chars)
    assert swapped != valid
    assert not is_valid_tracking_number(swapped)


def test_wrong_check_char_is_rejected() -> None:
    number = normalize_tracking_number(generate_tracking_number())
    good_check = number[-1]
    bad_check = "2" if good_check != "2" else "3"
    assert not is_valid_tracking_number(number[:-1] + bad_check)


def test_wrong_prefix_is_rejected() -> None:
    number = generate_tracking_number()
    assert not is_valid_tracking_number("ABC" + number[3:])


def test_wrong_length_is_rejected() -> None:
    number = generate_tracking_number()
    assert not is_valid_tracking_number(number[:-1])
    assert not is_valid_tracking_number(number + "2")


def test_characters_outside_alphabet_are_rejected() -> None:
    assert not is_valid_tracking_number("SND-0OIL-2345-6")
