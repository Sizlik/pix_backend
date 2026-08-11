import pytest

from manager.phone_numbers import normalize_phone, phone_search_variants


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("+7 (999) 123-45-67", "79991234567"),
        ("79991234567", "79991234567"),
        ("8 999 123 45 67", "79991234567"),
        ("9991234567", "79991234567"),
        ("+48 123 456 789", "48123456789"),
        ("extension-only", ""),
    ],
)
def test_normalize_phone(value, expected):
    assert normalize_phone(value) == expected


def test_phone_search_variants_cover_common_russian_formats_without_duplicates():
    assert phone_search_variants("+7 (999) 123-45-67") == (
        "+7 (999) 123-45-67",
        "+7 999 123-45-67",
        "+7 999 123 45 67",
        "+79991234567",
        "79991234567",
        "8 (999) 123-45-67",
        "8 999 123-45-67",
        "89991234567",
    )


def test_phone_search_variants_keep_original_and_digits_for_other_numbers():
    assert phone_search_variants("+48 123 456 789") == (
        "+48 123 456 789",
        "48123456789",
    )
    assert phone_search_variants("not-a-phone") == ("not-a-phone",)
    assert phone_search_variants("   ") == ()
