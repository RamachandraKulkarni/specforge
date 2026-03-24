"""Haiku-powered: is this screen a duplicate of one we've already analyzed?"""

import hashlib
from dataclasses import dataclass, field

from specforge.ai.gemini_client import GeminiClient
from specforge.ai.image_utils import screenshot_bytes_to_vision
from specforge.ai.prompt_manager import PromptManager


@dataclass
class DuplicateResult:
    verdict: str = "different"  # duplicate | variant | different
    is_duplicate: bool = False
    duplicate_of: str | None = None
    similarity_score: float = 0.0
    variant_differences: list = field(default_factory=list)
    reason: str = ""


class DuplicateDetector:
    """Haiku-powered: is this screen a duplicate of one we've already analyzed?"""

    def __init__(
        self,
        ai: GeminiClient,
        prompt_manager: PromptManager,
        config: dict,
    ):
        self.ai = ai
        self.pm = prompt_manager
        self.config = config

    def _dom_hash(self, screen: dict) -> str:
        dom = screen.get("dom_structure", screen.get("url", ""))
        return hashlib.md5(str(dom).encode()).hexdigest()

    def _compute_dom_similarity(self, new_screen: dict, existing_screens) -> tuple[float, dict | None]:
        new_hash = self._dom_hash(new_screen)
        best_score = 0.0
        best_match = None

        for existing in existing_screens:
            existing_hash = self._dom_hash(existing)
            if new_hash == existing_hash:
                return 1.0, existing
            # Simple character-level similarity as a fast heuristic
            common = sum(a == b for a, b in zip(new_hash, existing_hash))
            score = common / max(len(new_hash), len(existing_hash))
            if score > best_score:
                best_score = score
                best_match = existing

        return best_score, best_match

    async def is_duplicate(
        self, new_screen: dict, existing_screens
    ) -> DuplicateResult:
        existing_list = list(existing_screens)
        if not existing_list:
            return DuplicateResult()

        similarity, best_match = self._compute_dom_similarity(new_screen, existing_list)

        if similarity < 0.3:
            return DuplicateResult(verdict="different")

        if similarity > 0.95 and best_match:
            return DuplicateResult(
                verdict="duplicate",
                is_duplicate=True,
                duplicate_of=best_match.get("id"),
                similarity_score=similarity,
            )

        # Ambiguous — ask Haiku to compare visually
        if best_match:
            return await self._haiku_visual_compare(new_screen, best_match, similarity)

        return DuplicateResult()

    async def _haiku_visual_compare(
        self, new_screen: dict, best_match: dict, dom_similarity: float
    ) -> DuplicateResult:
        variables = {
            "url_a": best_match.get("url", ""),
            "title_a": best_match.get("title", ""),
            "table_count_a": best_match.get("table_count", 0),
            "button_count_a": best_match.get("button_count", 0),
            "url_b": new_screen.get("url", ""),
            "title_b": new_screen.get("title", ""),
            "table_count_b": new_screen.get("table_count", 0),
            "button_count_b": new_screen.get("button_count", 0),
            "dom_similarity": round(dom_similarity, 2),
        }

        system = (
            "You compare two web application screenshots to determine if they show the same screen "
            "(duplicate), a variant of the same screen, or completely different screens. "
            "Respond with ONLY valid JSON."
        )
        prompt = self.pm.load("decisions.duplicate_detection", variables)

        images = []
        if best_match.get("screenshot_bytes"):
            images.append(screenshot_bytes_to_vision(best_match["screenshot_bytes"]))
        if new_screen.get("screenshot_bytes"):
            images.append(screenshot_bytes_to_vision(new_screen["screenshot_bytes"]))

        if images:
            result = await self.ai.call_with_vision(
                "gemini-3.1-flash-lite-preview", system, prompt, images, max_tokens=300
            )
        else:
            result = await self.ai.haiku(system, prompt, max_tokens=300)

        parsed = result.get("parsed") or {}
        verdict = parsed.get("verdict", "different")

        return DuplicateResult(
            verdict=verdict,
            is_duplicate=verdict == "duplicate",
            duplicate_of=parsed.get("duplicate_of"),
            similarity_score=float(parsed.get("similarity", dom_similarity)),
            variant_differences=parsed.get("variant_differences", []),
            reason=parsed.get("reason", ""),
        )
