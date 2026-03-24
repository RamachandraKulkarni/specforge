"""Haiku-powered decision routing — central hub for all autonomous crawl decisions."""

from specforge.ai.gemini_client import GeminiClient
from specforge.ai.prompt_manager import PromptManager
from specforge.decisions.ambiguity_resolver import AmbiguityResolver
from specforge.decisions.click_decider import ClickDecider, ClickDecision
from specforge.decisions.depth_controller import DepthController, DepthDecision
from specforge.decisions.duplicate_detector import DuplicateDetector, DuplicateResult
from specforge.decisions.priority_ranker import PriorityRanker


class DecisionEngine:
    """Central hub: wires up all decision components with shared AI client."""

    def __init__(
        self,
        ai: GeminiClient,
        prompt_manager: PromptManager,
        config: dict,
    ):
        self.ai = ai
        self.pm = prompt_manager
        self.config = config

        self.click_decider = ClickDecider(ai, prompt_manager, config)
        self.duplicate_detector = DuplicateDetector(ai, prompt_manager, config)
        self.priority_ranker = PriorityRanker(ai, prompt_manager, config)
        self.depth_controller = DepthController(ai, prompt_manager, config)
        self.ambiguity_resolver = AmbiguityResolver(ai, prompt_manager, config)

    async def should_click(self, element: dict, screen_context: dict, **kwargs) -> ClickDecision:
        return await self.click_decider.should_click(element, screen_context, **kwargs)

    async def is_duplicate(self, new_screen: dict, existing_screens) -> DuplicateResult:
        return await self.duplicate_detector.is_duplicate(new_screen, existing_screens)

    async def rank_elements(self, elements: list, screen_context: dict, **kwargs) -> list:
        return await self.priority_ranker.rank_elements(elements, screen_context, **kwargs)

    async def should_continue(self, state: dict) -> DepthDecision:
        return await self.depth_controller.should_continue_exploring(state)

    async def resolve_ambiguity(self, result: dict, context: dict, task_type: str) -> dict:
        return await self.ambiguity_resolver.resolve(result, context, task_type)
