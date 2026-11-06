"""Identifier normalization, so the same person typed two ways still matches."""
import re
from typing import Optional

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    value = raw.strip().lower()
    return value if _EMAIL.match(value) else None


def normalize_phone(raw: Optional[str]) -> Optional[str]:
    """Digits only; a leading US country code on an 11-digit number is dropped
    so "+1 (206) 555-0111" and "206-555-0111" compare equal. Returns None for
    anything shorter than 7 digits."""
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits if len(digits) >= 7 else None
