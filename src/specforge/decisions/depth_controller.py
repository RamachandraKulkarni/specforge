"""Haiku-powered: controls exploration depth to prevent runaway crawls."""

from dataclasses import dataclass
from typing import Literal

from specforge.ai.gemini_client import GeminiClient
from specforge.ai.prompt_manager import PromptManager


@dataclass
class DepthDecision:
    action: Literal["go_deeper", "go_wider", "skip_branch", "wrap_up"] = "go_deeper"
    reason: str = ""
    recommended_next: str = ""


class DepthController:
    """Haiku-powered: controls exploration depth to prevent runaway crawls."""

    def __init__(
        self,
        ai: GeminiClient,
        prompt_manager: PromptManager,
        config: dict,
    ):
        self.ai = ai
        self.pm = prompt_manager
        self.max_depth = config.get("extraction", {}).get("crawl", {}).get("max_depth", 5)
        self.max_cost = config.get("ai", {}).get("budget", {}).get("max_cost_usd", 15.0)

    async def should_continue_exploring(
        self, exploration_state: dict
    ) -> DepthDecision:
        variables = {
            "current_depth": exploration_state.get("current_depth", 0),
            "max_depth": self.max_depth,
            "total_screens": exploration_state.get("total_screens", 0),
            "analyzed_screens": exploration_state.get("analyzed_screens", 0),
            "recent_new_tables": exploration_state.get("recent_new_tables", 0),
            "recent_new_buttons": exploration_state.get("recent_new_buttons", 0),
            "recent_new_endpoints": exploration_state.get("recent_new_endpoints", 0),
            "cost_so_far": round(exploration_state.get("cost_so_far", 0.0), 3),
            "max_cost": self.max_cost,
            "time_elapsed": exploration_state.get("time_elapsed", 0),
            "queue_size": exploration_state.get("queue_size", 0),
        }

        system = (
            "You are a crawl depth controller. Respond with ONLY valid JSON."
        )
        prompt = self.pm.load("decisions.depth_control", variables)

        result = await self.ai.haiku(system, prompt, max_tokens=200)
        parsed = result.get("parsed") or {}

        return DepthDecision(
            action=parsed.get("action", "go_deeper"),
            reason=parsed.get("reason", ""),
            recommended_next=parsed.get("recommended_next", ""),
        )
