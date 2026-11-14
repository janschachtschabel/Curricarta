"""What a measuring command may print (plan H-3, global rule 11): numbers, truth values, null and codes of
``LEAF`` - no space, so no wording, quote or note can pass. Each command checks its output with ``closed``
before it prints, and refuses where a key or leaf is other."""

import re

LEAF = r"[A-Za-z0-9_.:/+-]{1,60}"  # no space: no wording passes
NOT_CLOSED = "report_not_closed"  # the refusal's code


def token(value: object) -> str | None:
    """The value where it is a code of LEAF, else None."""
    return value if isinstance(value, str) and re.fullmatch(LEAF, value) else None


def closed(value: object) -> None:
    """ValueError where a key or leaf is other than a number, a truth value, null or a code of LEAF."""
    if isinstance(value, dict):
        for key, inner in value.items():
            closed(key)
            closed(inner)
    elif isinstance(value, list | tuple):
        for inner in value:
            closed(inner)
    elif not (value is None or isinstance(value, bool | int | float) or token(value) is not None):
        raise ValueError("a report holds counts, rates and codes alone")
