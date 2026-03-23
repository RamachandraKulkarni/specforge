"""Haiku-powered: rank elements by spec relevance and exploration value."""

from specforge.ai.anthropic_client import AnthropicClient
from specforge.ai.prompt_manager import PromptManager


class PriorityRanker:
    """Haiku-powered: rank elements by spec relevance and exploration value."""

    def __init__(
        self,
        ai: AnthropicClient,
        prompt_manager: PromptManager,
        config: dict,
    ):
        self.ai = ai
        self.pm = prompt_manager
        self.iso = config.get("target", {}).get("iso", "")
        self.module = config.get("target", {}).get("module", "")

    async def rank_elements(
        self,
        elements: list[dict],
        screen_context: dict,
        already_explored: list | None = None,
        budget_remaining: int = 100,
    ) -> list[dict]:
        if not elements:
            return []

        variables = {
            "element_count": len(elements),
            "screen_title": screen_context.get("title", ""),
            "screen_url": screen_context.get("url", ""),
            "iso": self.iso,
            "module": self.module,
            "elements_json": elements,
            "view_flow_type": screen_context.get("view_flow_type", "unknown"),
            "table_count": screen_context.get("table_count", 0),
            "already_explored": already_explored or [],
            "budget_remaining": budget_remaining,
        }

        system = (
            "You rank UI elements by their value for generating a specification document. "
            "Respond with ONLY valid JSON."
        )
        prompt = self.pm.load("decisions.priority_ranking", variables)

        result = await self.ai.haiku(system, prompt, max_tokens=600)
        parsed = result.get("parsed") or {}

        rankings: dict[str, int] = {}
        for item in parsed.get("rankings", []):
            rankings[item.get("element_id", "")] = int(item.get("priority", 5))

        return sorted(
            elements,
            key=lambda e: rankings.get(e.get("element_id", ""), 5),
            reverse=True,
        )
