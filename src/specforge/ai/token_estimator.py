"""Rough token estimation before API calls to avoid context-limit surprises."""


# Characters-per-token approximation (conservative)
_CHARS_PER_TOKEN = 3.5
# Approximate tokens consumed by a 500 KB image in the Gemini vision API
_IMAGE_TOKENS = 1600


def estimate_text_tokens(text: str) -> int:
    return max(1, int(len(text) / _CHARS_PER_TOKEN))


def estimate_image_tokens(num_images: int = 1) -> int:
    return _IMAGE_TOKENS * num_images


def estimate_call_tokens(
    system: str,
    user_text: str,
    num_images: int = 0,
) -> int:
    """Estimate total input tokens for an API call."""
    return (
        estimate_text_tokens(system)
        + estimate_text_tokens(user_text)
        + estimate_image_tokens(num_images)
    )


def fits_in_context(
    system: str,
    user_text: str,
    num_images: int = 0,
    context_limit: int = 190_000,
) -> bool:
    return estimate_call_tokens(system, user_text, num_images) < context_limit
