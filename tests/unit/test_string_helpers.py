"""
unit tests for reverse_geolocate.utils.string_helpers
"""

import unicodedata
from collections.abc import Iterator

import pytest

from reverse_geolocate.utils import string_helpers
from reverse_geolocate.utils.string_helpers import (
    char_width,
    format_len,
    is_latin,
    only_latin_chars,
    shorten_path,
    shorten_string,
    string_len_cjk,
)


@pytest.fixture(autouse=True)
def clear_latin_cache() -> Iterator[None]:
    """the latin lookup cache is module global, keep tests independent"""
    string_helpers.cache_latin_letters.clear()
    yield
    string_helpers.cache_latin_letters.clear()


# MARK: string_len_cjk
@pytest.mark.parametrize(
    ("string", "expected"),
    [
        ("", 0),
        ("abc", 3),
        ("Tōkyō", 5),
        ("東京", 4),
        ("東京 Tokyo", 10),
        # full width latin letters are double width (F)
        ("ＡＢ", 4),
        # half width katakana are single width (H)
        ("ｱｲ", 2),
    ],
)
def test_string_len_cjk(string: str, expected: int) -> None:
    assert string_len_cjk(string) == expected


# MARK: shorten_string
def test_shorten_string_fits_unchanged() -> None:
    assert shorten_string("abc", width=3) == "abc"
    assert shorten_string("abc", width=10) == "abc"


def test_shorten_string_empty() -> None:
    assert shorten_string("", width=5) == ""


def test_shorten_string_ascii() -> None:
    result = shorten_string("abcdefghij", width=5)
    assert result == "abc.."
    assert string_len_cjk(result) == 5


def test_shorten_string_custom_placeholder() -> None:
    assert shorten_string("abcdefghij", width=6, placeholder="~") == "abcde~"


def test_shorten_string_cjk_by_display_width() -> None:
    # width 12 -> 7: room for 5 display columns, the third CJK char would need 6
    result = shorten_string("東京都渋谷区", width=7)
    assert result == "東京.."
    assert string_len_cjk(result) <= 7


def test_shorten_string_cjk_fits_unchanged() -> None:
    # 4 characters, but 8 display columns -> fits exactly into 8
    assert shorten_string("東京都区", width=8) == "東京都区"


def test_shorten_string_cjk_too_wide_by_display_width() -> None:
    # 4 characters fit by count, but not by display width
    assert shorten_string("東京都区", width=7) == "東京.."


def test_shorten_string_non_string_input() -> None:
    # values are converted with str()
    assert shorten_string(1234567, width=5) == "123.."  # type: ignore
    assert shorten_string(123, width=5) == "123"  # type: ignore


@pytest.mark.parametrize(
    ("string", "width", "expected"),
    [
        # width equal or less than the placeholder: cut without placeholder
        ("abcdef", 2, "ab"),
        ("abcdef", 1, "a"),
        ("abcdef", 0, ""),
        ("abcdef", -1, ""),
        # a double width char does not fit into 1
        ("東京", 1, ""),
        ("東京都", 2, "東"),
        # one more than the placeholder: placeholder is used again
        ("abcdef", 3, "a.."),
    ],
)
def test_shorten_string_width_not_more_than_placeholder(string: str, width: int, expected: str) -> None:
    assert shorten_string(string, width=width) == expected


def test_shorten_string_width_not_more_than_custom_placeholder() -> None:
    assert shorten_string("abcdef", width=3, placeholder="...") == "abc"
    assert shorten_string("abcdef", width=4, placeholder="...") == "a..."


def test_shorten_string_fits_with_width_smaller_than_placeholder() -> None:
    # a string that fits is never changed
    assert shorten_string("a", width=1) == "a"


@pytest.mark.parametrize("width", range(15))
def test_shorten_string_never_wider_than_width(width: int) -> None:
    for string in ("abcdefghijklmnop", "東京都渋谷区神南一丁目", "Tokyo 東京都 Shibuya"):
        assert string_len_cjk(shorten_string(string, width=width)) <= width


# MARK: is_latin
@pytest.mark.parametrize("char", ["a", "Z", "é", "ō", "ß"])
def test_is_latin_true(char: str) -> None:
    assert is_latin(char) is True


@pytest.mark.parametrize("char", ["あ", "東", "Ж", "א", "α", "1"])
def test_is_latin_false(char: str) -> None:
    assert is_latin(char) is False


def test_is_latin_uses_cache() -> None:
    assert "a" not in string_helpers.cache_latin_letters
    is_latin("a")
    assert string_helpers.cache_latin_letters["a"] is True
    # a cached value is returned as is, without a new unicode lookup
    string_helpers.cache_latin_letters["a"] = False
    assert is_latin("a") is False


# MARK: only_latin_chars
@pytest.mark.parametrize(
    ("string", "expected"),
    [
        ("Tokyo", True),
        ("Tōkyō", True),
        ("München", True),
        ("Saint-Étienne 2", True),
        ("東京", False),
        ("Tokyo 東京", False),
        ("Москва", False),
        ("ירושלים", False),
        # non letters are ignored
        ("", True),
        ("123 - 456", True),
    ],
)
def test_only_latin_chars(string: str, expected: bool) -> None:
    assert only_latin_chars(string) is expected


# MARK: format_len
@pytest.mark.parametrize(
    ("string", "length", "expected"),
    [
        ("abc", 10, 10),
        ("", 10, 10),
        ("東京", 10, 8),
        ("東京 Tokyo", 20, 18),
    ],
)
def test_format_len(string: str, length: int, expected: int) -> None:
    assert format_len(string, length) == expected


def test_format_len_aligns_columns() -> None:
    # padding with the adjusted length gives the same display width
    for string in ("Tokyo", "東京", "東京 Tokyo"):
        padded = f"{string:<{format_len(string, 15)}}"
        assert string_len_cjk(padded) == 15


# MARK: shorten_path
def test_shorten_path_fits_unchanged() -> None:
    assert shorten_path("/a/b/c.xmp", length=30) == "/a/b/c.xmp"


def test_shorten_path_file_only() -> None:
    assert shorten_path("/some/folder/file.xmp", length=30, file_only=True) == "file.xmp"


def test_shorten_path_path_only() -> None:
    assert shorten_path("/some/folder/file.xmp", length=30, path_only=True) == "/some/folder"


def test_shorten_path_file_and_path_only_raises() -> None:
    with pytest.raises(ValueError):
        shorten_path("/a/b.xmp", file_only=True, path_only=True)


def test_shorten_path_long_path_keeps_right_side() -> None:
    result = shorten_path("/very/long/folder/structure/file.xmp", length=15)
    assert result == ".. ure/file.xmp"
    assert len(result) == 15


def test_shorten_path_exact_length_unchanged() -> None:
    path = "/abc/def.xmp"
    assert shorten_path(path, length=len(path)) == path


@pytest.mark.parametrize(
    ("length", "expected"),
    [
        (0, ""),
        (1, "."),
        (2, ".."),
        (3, ".. "),
        (4, ".. h"),
    ],
)
def test_shorten_path_very_small_length(length: int, expected: str) -> None:
    assert shorten_path("/a/long/path", length=length) == expected


def test_shorten_path_cjk_by_display_width() -> None:
    result = shorten_path("/写真/東京フォルダ", length=10, path_only=False)
    # 7 columns for the path part: 3 CJK characters (6 columns), the 4th would need 8
    assert result == ".. ォルダ"
    assert string_len_cjk(result) <= 10


@pytest.mark.parametrize("length", range(25))
def test_shorten_path_never_wider_than_length(length: int) -> None:
    for path in ("/Users/someone/Pictures/2026/file.xmp", "/写真/東京フォルダ/渋谷区/写真.xmp"):
        assert string_len_cjk(shorten_path(path, length=length)) <= length


# MARK: decomposed (NFD) characters
NFC_NAME = unicodedata.normalize("NFC", "Zürich Café")
NFD_NAME = unicodedata.normalize("NFD", "Zürich Café")


@pytest.mark.parametrize(
    ("char", "expected"),
    [("a", 1), ("ü", 1), ("東", 2), ("Ａ", 2), ("\u0308", 0), ("\u0301", 0), ("\u3099", 0)],
)
def test_char_width(char: str, expected: int) -> None:
    assert char_width(char) == expected


def test_string_len_nfd_same_as_nfc() -> None:
    assert len(NFD_NAME) == len(NFC_NAME) + 2
    assert string_len_cjk(NFD_NAME) == string_len_cjk(NFC_NAME) == 11


def test_string_len_no_precomposed_form() -> None:
    # "n" + combining diaeresis has no composed form, NFC does not help
    assert len(unicodedata.normalize("NFC", "n\u0308")) == 2
    assert string_len_cjk("n\u0308") == 1


def test_string_len_japanese_dakuten_nfd() -> None:
    # "ガ" decomposed: "カ" + combining voiced sound mark
    assert string_len_cjk(unicodedata.normalize("NFD", "ガ")) == 2


def test_format_len_nfd_aligned() -> None:
    padded = f"{NFD_NAME:<{format_len(NFD_NAME, 15)}}"
    assert string_len_cjk(padded) == 15


def test_shorten_string_nfd() -> None:
    # the accent stays with its base character
    assert shorten_string(NFD_NAME, width=5) == unicodedata.normalize("NFD", "Zür..")
    assert shorten_string(NFD_NAME, width=11) == NFD_NAME


def test_shorten_string_nfd_base_cut_drops_accent() -> None:
    # "u" does not fit: its accent is not added alone
    assert shorten_string(unicodedata.normalize("NFD", "Zü"), width=1) == "Z"


def test_shorten_path_nfd_fits() -> None:
    path = f"/photos/{NFD_NAME}.xmp"
    assert shorten_path(path, length=string_len_cjk(path)) == path


def test_shorten_path_nfd_no_lone_accent() -> None:
    # cut right after the base character: the accent must not start the result alone
    path = unicodedata.normalize("NFD", "/a/ü.xmp")
    result = shorten_path(path, length=7)
    assert result == ".. .xmp"
    assert not unicodedata.combining(result[3])


@pytest.mark.parametrize("length", range(25))
def test_shorten_path_nfd_never_wider(length: int) -> None:
    for path in (f"/photos/{NFD_NAME}/{NFD_NAME}.xmp", unicodedata.normalize("NFD", "/写真/ガイド/ポスター.xmp")):
        result = shorten_path(path, length=length)
        assert string_len_cjk(result) <= length
        if result.startswith(".. ") and len(result) > 3:
            assert not unicodedata.combining(result[3])


# __END__
