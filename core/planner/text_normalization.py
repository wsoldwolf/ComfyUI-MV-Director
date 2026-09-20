"""Narrow presentation cleanup explicitly requested for generated Shot text."""

import re


_TRAILING_CONTINUATION = re.compile(r"[ \t\u3000]+\\[ \t\u3000]*\Z")


def strip_generated_line_continuation(text: str) -> str:
    """Remove only a whitespace-delimited, single trailing backslash.

    Interior escapes, paths, quoted symbols and doubled backslashes are not
    matched. Call only for generated Action/Camera, never author-owned EMD.
    Do not turn an otherwise empty record into an apparently valid deletion.
    """
    match = _TRAILING_CONTINUATION.search(text)
    if match and text[:match.start()].strip():
        return text[:match.start()]
    return text
