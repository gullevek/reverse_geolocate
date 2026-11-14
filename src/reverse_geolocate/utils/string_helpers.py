"""
various string helpers1
"""

import os
import unicodedata

# this is for looking up if string is non latin letters
# this is used by isLatin and onlyLatinChars
cache_latin_letters: dict[str, bool] = {}


def shorten_string(string: str, width: int, placeholder: str = "..") -> str:
    """
    shortens a string to width and attached placeholder
    if the width is equal or less than the placeholder width, the placeholder is not used
    and the string is only cut to width

    Args:
        string(str): string to shorten
        width (int): length th shorten to
        placeholder (str, optional): optional string for removed shortend part. Defaults to '..'.

    Returns:
        string: shortened string
    """
    # get the length with double byte charactes
    string_length_cjk = string_len_cjk(str(string))
    # if double byte width is too big
    if string_length_cjk > width:
        # no room for any text next to the placeholder, cut without placeholder
        if width <= string_len_cjk(placeholder):
            placeholder = ""
        # set current length and output string
        cur_len = 0
        out_string = ""
        # loop through each character
        for char in str(string):
            # set the current length if we add the character
            cur_len += 2 if unicodedata.east_asian_width(char) in "WF" else 1
            # if the new length is smaller than the output length to shorten too add the char
            if cur_len <= (width - string_len_cjk(placeholder)):
                out_string += char
        # return string with new width and placeholder
        return f"{out_string}{placeholder}"
    else:
        return str(string)


def string_len_cjk(string: str) -> int:
    """
    because len on string in python counts characters but we need the width
    count for formatting, we count two for a double byte characters

    Args:
        string (str): string to check length

    Returns:
        int: length including double count for double width characters
    """
    # return string len including double count for double width characters
    return sum(1 + (unicodedata.east_asian_width(c) in "WF") for c in string)


def is_latin(uchr: str) -> bool:
    """
    checks via the unciode class if a character is LATIN char based

    from
    https://stackoverflow.com/a/3308844/7811993

    Args:
        uchr (str): character to check

    Returns:
        bool: True if LATIN char, False otherwise
    """
    try:
        # if we found in the dictionary return
        return cache_latin_letters[uchr]
    except KeyError:
        # find LATIN in uncide type returned and set in dictionary for this character
        return cache_latin_letters.setdefault(uchr, "LATIN" in unicodedata.name(uchr))


def only_latin_chars(unistr: str) -> bool:
    """
    chekcs if a string is based on LATIN chars. No for any CJK, Cyrillic, Hebrew, etc

    from:
    https://stackoverflow.com/a/3308844/7811993

    Args:
        unistr (str): string

    Returns:
        bool: True/False for if string is LATIN char based
    """
    return all(is_latin(uchr) for uchr in unistr if uchr.isalpha())


def format_len(string: str, length: int) -> int:
    """
    in case of CJK characters we need to adjust the format length dynamically
    calculate correct length based on string given

    Args:
        string (str): string
        length (int): format length

    Returns:
        int: adjusted format length
    """
    # returns length udpated for string with double byte characters
    # get string length normal, get string length including double byte characters
    # then subtract that from the original length
    return length - (string_len_cjk(string) - len(string))


# MARK: shorten path
def shorten_path(path: str, length: int = 30, file_only: bool = False, path_only: bool = False) -> str:
    """
    shortens a path from the left so it fits into length (display width, CJK = 2)
    if file_only is set only the file name is used, if path_only is set only the folder

    Args:
        path (str): path
        length (int, optional): maximum display width to shorten to. Defaults to 30.
        file_only (bool, optional): only use the file name. Defaults to False.
        path_only (bool, optional): only use the folder. Defaults to False.

    Raises:
        ValueError: if file_only and path_only are both set

    Returns:
        str: shortened path with ".. " in front if it was too long
    """
    if file_only and path_only:
        raise ValueError("shorten_path: file_only and path_only cannot be set both")
    placeholder = ".. "
    if file_only:
        path = os.path.split(path)[1]
    elif path_only:
        path = os.path.split(path)[0]
    if string_len_cjk(path) <= length:
        return path
    # not even room for the placeholder
    if length <= len(placeholder):
        return placeholder[: max(0, length)]
    # available width for the path part after the placeholder
    available = max(0, length - len(placeholder))
    # collect characters from the right as long as the display width fits
    # (slicing by character count would be wrong for double width CJK characters)
    # the path is wider than available (checked above), so this always stops before cut reaches 0
    width = 0
    cut = len(path)
    while cut > 0 and width + string_len_cjk(path[cut - 1]) <= available:
        cut -= 1
        width += string_len_cjk(path[cut])
    return f"{placeholder}{path[cut:]}"


# __END__
