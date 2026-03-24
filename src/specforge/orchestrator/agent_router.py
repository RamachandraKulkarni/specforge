"""Routes tasks to the appropriate model tier based on task type and complexity."""

from specforge.ai.gemini_client import GeminiClient


class AgentRouter:
    """Determine which model tier to use for a given task."""

    TIER_MAP = {
        "click_decision": "haiku",
        "duplicate_detection": "haiku",
        "priority_ranking": "haiku",
        "depth_control": "haiku",
        "screen_classification": "haiku",
        "table_analysis": "haiku",
        "header_behavior": "haiku",
        "filter_type": "haiku",
        "validation_rule": "haiku",
        "api_field_mapping": "haiku",
        "navigation_detection": "haiku",
        "ambiguity_resolution": "sonnet",
        "interaction_analysis": "sonnet",
        "spec_assembly": "opus",
    }

    def __init__(self, ai: GeminiClient):
        self.ai = ai

    def get_tier(self, task_type: str) -> str:
        return self.TIER_MAP.get(task_type, "haiku")

    async def route(self, task_type: str, system: str, content, **kwargs):
        tier = self.get_tier(task_type)
        if tier == "haiku":
            return await self.ai.haiku(system, content, **kwargs)
        elif tier == "sonnet":
            return await self.ai.sonnet(system, content, **kwargs)
        else:
            return await self.ai.opus(system, content, **kwargs)
