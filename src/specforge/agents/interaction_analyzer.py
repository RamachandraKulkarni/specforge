"""Agent 4: Click behavior analysis (Sonnet) — state transitions and interactions."""

import asyncio
from itertools import islice

from specforge.ai.gemini_client import GeminiClient
from specforge.ai.image_utils import screenshot_bytes_to_vision
from specforge.ai.prompt_manager import PromptManager


def _chunked(iterable, size):
    it = iter(iterable)
    while True:
        chunk = list(islice(it, size))
        if not chunk:
            break
        yield chunk


class InteractionAnalyzer:
    """Sonnet-powered: analyzes state transitions and click behaviors."""

    SYSTEM_PROMPT = (
        "You analyze UI interactions — what happens when users click buttons, submit forms, "
        "switch tabs, apply filters. You receive before/after state captures and produce "
        "detailed interaction specifications including API calls, UI state changes, "
        "preconditions, and error handling. Respond with ONLY valid JSON."
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

    async def analyze_all(self, transitions: list[dict]) -> list[dict]:
        """Group transitions by source screen and analyze in Sonnet batches."""
        from collections import defaultdict

        by_screen: dict[str, list] = defaultdict(list)
        for t in transitions:
            by_screen[t.get("from_screen", "unknown")].append(t)

        results = []
        for screen_id, screen_transitions in by_screen.items():
            for batch in _chunked(screen_transitions, 5):
                batch_result = await self._analyze_batch(screen_id, batch)
                results.extend(batch_result)
        return results

    async def _analyze_batch(self, screen_id: str, batch: list[dict]) -> list[dict]:
        variables = {
            "batch_size": len(batch),
            "screen_id": screen_id,
            "page_url": batch[0].get("before_state", {}).get("url", "") if batch else "",
            "view_flow_type": batch[0].get("view_flow_type", "unknown") if batch else "unknown",
            "screen_purpose": batch[0].get("screen_purpose", "") if batch else "",
            "interactions": [
                {
                    "index": i + 1,
                    "element_type": t.get("trigger", {}).get("tag", "button"),
                    "element_text": t.get("trigger", {}).get("text", ""),
                    "element_selector": t.get("trigger", {}).get("selector", ""),
                    "category": t.get("trigger", {}).get("category", "MISC"),
                    "sub_category": t.get("trigger", {}).get("sub_category", ""),
                    "elements_added": [],
                    "elements_removed": [],
                    "elements_modified": [],
                    "text_changes": [],
                    "network_requests": t.get("network_requests", [])[:5],
                    "url_before": t.get("before_state", {}).get("url", ""),
                    "url_after": t.get("after_state", {}).get("url", ""),
                }
                for i, t in enumerate(batch)
            ],
        }

        prompt = self.pm.load("agents.interaction_analyzer", variables)

        images = []
        for t in batch[:2]:  # Max 2 before/after pairs per batch call
            before_bytes = t.get("before_screenshot_bytes")
            after_bytes = t.get("after_screenshot_bytes")
            if before_bytes:
                images.append(screenshot_bytes_to_vision(before_bytes))
            if after_bytes:
                images.append(screenshot_bytes_to_vision(after_bytes))

        if images:
            result = await self.ai.call_with_vision(
                "gemini-3-flash-preview", self.SYSTEM_PROMPT, prompt, images, max_tokens=3000
            )
        else:
            result = await self.ai.sonnet(self.SYSTEM_PROMPT, prompt, max_tokens=3000)

        parsed = result.get("parsed") or {}
        return parsed.get("interactions", [])
