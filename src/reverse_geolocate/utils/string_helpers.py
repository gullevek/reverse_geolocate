"""
various string helpers1
"""

import unicodedata

# this is for looking up if string is non latin letters
# this is used by isLatin and onlyLatinChars
cache_latin_letters = {}


def shorten_string(string, width, placeholder=".."):
    """
    shortens a string to width and attached placeholder

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
        # set current length and output string
        cur_len = 0
        out_string = ""
        # loop through each character
        for char in str(string):
            # set the current length if we add the character
            cur_len += 2 if unicodedata.east_asian_width(char) in "WF" else 1
            # if the new length is smaller than the output length to shorten too add the char
            if cur_len <= (width - len(placeholder)):
                out_string += char
        # return string with new width and placeholder
        return f"{out_string}{placeholder}"
    else:
        return str(string)


def string_len_cjk(string):
    """
    because len on string in python counts characters but we need the width
    count for formatting, we count two for a double byte characters

    Args:
        string (string): string to check length

    Returns:
        int: length including double count for double width characters
    """
    # return string len including double count for double width characters
    return sum(1 + (unicodedata.east_asian_width(c) in "WF") for c in string)


def is_latin(uchr):
    """
    checks via the unciode class if a character is LATIN char based

    from
    https://stackoverflow.com/a/3308844/7811993

    Args:
        uchr (str): _description_

    Returns:
        str: flagged LATIN or not char
    """
    try:
        # if we found in the dictionary return
        return cache_latin_letters[uchr]
    except KeyError:
        # find LATIN in uncide type returned and set in dictionary for this character
        return cache_latin_letters.setdefault(uchr, "LATIN" in unicodedata.name(uchr))


def only_latin_chars(unistr):
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


def format_len(string, length):
    """
    in case of CJK characters we need to adjust the format length dynamically
    calculate correct length based on string given

    Args:
        string (str): string
        length (int): format length

    Returns:
        int: adjusted format legnth
    """
    # returns length udpated for string with double byte characters
    # get string length normal, get string length including double byte characters
    # then subtract that from the original length
    return length - (string_len_cjk(string) - len(string))
