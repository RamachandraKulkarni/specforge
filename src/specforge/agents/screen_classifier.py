"""Agent 2: Screen type classification (Haiku) with confidence-based escalation."""

import asyncio

from specforge.ai.gemini_client import GeminiClient
from specforge.ai.image_utils import screenshot_bytes_to_vision
from specforge.ai.prompt_manager import PromptManager
from specforge.decisions.ambiguity_resolver import AmbiguityResolver


class ScreenClassifier:
    """Classify screens into structured categories using Haiku + escalation."""

    SYSTEM_PROMPT = (
        "You classify web application screens into structured categories for a UI specification "
        "generator. You analyze a screenshot alongside DOM metadata to determine the screen's "
        "purpose, layout structure, and button categories. "
        "You understand energy market management platforms (ISOs, FTRs, TCRs). "
        "Respond with ONLY valid JSON. No markdown, no explanation."
    )

    def __init__(
        self,
        ai: GeminiClient,
        prompt_manager: PromptManager,
        config: dict,
    ):
        self.ai = ai
        self.pm = prompt_manager
        self.config = config
        self.iso = config.get("target", {}).get("iso", "")
        self.module = config.get("target", {}).get("module", "")
        self.resolver = AmbiguityResolver(ai, prompt_manager, config)

    async def classify_all(self, screens: list[dict]) -> list[dict]:
        """Classify all screens in parallel (up to haiku concurrency limit)."""
        tasks = [self._classify_one(screen) for screen in screens]
        return await asyncio.gather(*tasks)

    async def _classify_one(self, screen: dict) -> dict:
        variables = {
            "iso": self.iso,
            "module": self.module,
            "screen_url": screen.get("url", ""),
            "screen_id": screen.get("id", ""),
            "dom_summary": str(screen.get("dom_summary", {}))[:3000],
            "tables_summary": screen.get("tables_detected", [])[:3],
            "clickable_elements": screen.get("dom_summary", {}).get("buttons", [])[:20],
        }

        prompt = self.pm.load("agents.screen_classifier", variables)

        screenshot_bytes = screen.get("screenshot_bytes")
        if screenshot_bytes:
            img = screenshot_bytes_to_vision(
                screenshot_bytes,
                self.config.get("extraction", {}).get("screenshot", {}).get("max_size_kb", 500),
            )
            result = await self.ai.call_with_vision(
                "gemini-3.1-flash-lite-preview", self.SYSTEM_PROMPT, prompt, [img], max_tokens=1000
            )
        else:
            result = await self.ai.haiku(self.SYSTEM_PROMPT, prompt, max_tokens=1000)

        # Confidence-based escalation
        confidence = float((result.get("parsed") or {}).get("confidence", 1.0))
        threshold = self.config.get("ai", {}).get("escalation", {}).get("confidence_threshold", 0.7)
        if confidence < threshold:
            result = await self.resolver.resolve(result, variables, task_type="screen_classification")

        parsed = result.get("parsed") or {}
        parsed["screen_id"] = screen.get("id", "")
        parsed["url"] = screen.get("url", "")
        return parsed
