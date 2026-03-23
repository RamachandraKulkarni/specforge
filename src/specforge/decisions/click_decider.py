"""Haiku-powered decision: should we click this element?"""

from dataclasses import dataclass, field
from typing import Literal

from specforge.ai.anthropic_client import AnthropicClient
from specforge.ai.prompt_manager import PromptManager


@dataclass
class ClickDecision:
    action: Literal["click", "skip", "defer"] = "skip"
    priority: int = 5
    reason: str = ""
    expected_result: str = "unknown"
    defer_until: str | None = None
    confidence: float = 1.0


class ClickDecider:
    """Haiku-powered decision: should we click this element?"""

    def __init__(
        self,
        ai: AnthropicClient,
        prompt_manager: PromptManager,
        config: dict,
    ):
        self.ai = ai
        self.pm = prompt_manager
        self.config = config
        self.iso = config.get("target", {}).get("iso", "")
        self.module = config.get("target", {}).get("module", "")
        self.max_depth = config.get("extraction", {}).get("crawl", {}).get("max_depth", 5)

    async def should_click(
        self,
        element_metadata: dict,
        screen_context: dict,
        visited_count: int = 0,
        current_depth: int = 0,
    ) -> ClickDecision:
        variables = {
            "iso": self.iso,
            "module": self.module,
            "tag": element_metadata.get("tag", ""),
            "text": element_metadata.get("text", ""),
            "aria_label": element_metadata.get("aria_label", ""),
            "classes": element_metadata.get("classes", []),
            "href": element_metadata.get("href", ""),
            "input_type": element_metadata.get("input_type", ""),
            "position": element_metadata.get("position", ""),
            "parent_context": element_metadata.get("parent_context", ""),
            "screen_url": screen_context.get("url", ""),
            "visited_count": visited_count,
            "current_depth": current_depth,
            "max_depth": self.max_depth,
        }

        system = (
            "You are a click-decision agent for an automated UI spec generator. "
            "Respond with ONLY valid JSON. No markdown fences, no explanation."
        )
        prompt = self.pm.load("decisions.click_decision", variables)

        result = await self.ai.haiku(system, prompt, max_tokens=300)
        parsed = result.get("parsed") or {}

        return ClickDecision(
            action=parsed.get("action", "skip"),
            priority=int(parsed.get("priority", 5)),
            reason=parsed.get("reason", ""),
            expected_result=parsed.get("expected_result", "unknown"),
            defer_until=parsed.get("defer_until"),
            confidence=float(parsed.get("confidence", 1.0)),
        )
