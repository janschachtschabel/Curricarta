"""Text as the stores keep it: PostgreSQL's text and jsonb take no NUL, UTF-8 no lone surrogate."""

import re

UNSTORABLE = re.compile(f"[{chr(0)}{chr(0xD800)}-{chr(0xDFFF)}]")


def storable(value: str | None) -> str | None:
    """``value`` as it is, or ValueError where the stores would refuse it: the validator of an input that
    goes on to a query as it came (a filter, an IRI), so that it ends as a refusal, not as an error there."""
    if value is not None and UNSTORABLE.search(value):
        raise ValueError("a NUL or a lone surrogate is no text the database keeps")
    return value
