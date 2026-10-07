import secrets
import string

ALPHABET = string.ascii_letters + string.digits


def generate_short_code(length: int = 7) -> str:
    """Generate an unpredictable URL-safe code from a base62 alphabet."""

    return "".join(secrets.choice(ALPHABET) for _ in range(length))
