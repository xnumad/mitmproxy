import typing

from mitmproxy.contentviews.base import TTextType, TViewLine
from mitmproxy.utils import strutils

KEY_MAX = 30


def format_dict(
        d: typing.Mapping[TTextType, TTextType]
) -> typing.Iterator[TViewLine]:
    """
    Helper function that transforms the given dictionary into a list of
        ("key",   key  )
        ("value", value)
    tuples, where key is padded to a uniform width.
    """
    max_key_len = max(len(k) for k in d.keys())
    max_key_len = min(max_key_len, KEY_MAX)
    for key, value in d.items():
        if isinstance(key, bytes):
            key += b":"
        else:
            key += ":"
        key = key.ljust(max_key_len + 2)
        yield [
            ("header", key),
            ("text", value)
        ]


def format_text(text: TTextType) -> typing.Iterator[TViewLine]:
    """
    Helper function that transforms bytes into the view output format.
    """
    for line in text.splitlines():
        yield [("text", line)]


