"""Adaptive element matching across ISOs — survives DOM changes."""

import hashlib
from difflib import SequenceMatcher


def generate_fingerprint(element_data: dict) -> str:
    """Create a stable fingerprint for an element."""
    key_parts = [
        element_data.get("tag", ""),
        element_data.get("text", "")[:50],
        element_data.get("aria_label", ""),
        "|".join(sorted(element_data.get("classes", []))),
        element_data.get("href", ""),
        element_data.get("input_type", ""),
    ]
    key = "::".join(key_parts)
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def similarity_score(fp_a: str, fp_b: str) -> float:
    """Rough similarity between two fingerprints (0.0–1.0)."""
    return SequenceMatcher(None, fp_a, fp_b).ratio()


def match_element(
    target_fingerprint: str,
    candidates: list[dict],
    threshold: float = 0.7,
) -> dict | None:
    """Find the best-matching candidate element by fingerprint similarity."""
    best_score = 0.0
    best_match = None

    for candidate in candidates:
        fp = candidate.get("fingerprint") or generate_fingerprint(candidate)
        score = similarity_score(target_fingerprint, fp)
        if score > best_score:
            best_score = score
            best_match = candidate

    if best_score >= threshold:
        return best_match
    return None
