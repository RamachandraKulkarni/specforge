"""Auto-escalation gate: Haiku uncertainty triggers Sonnet re-analysis."""

from specforge.ai.gemini_client import GeminiClient
from specforge.ai.prompt_manager import PromptManager


class AmbiguityResolver:
    """When Haiku confidence < threshold, escalate to Sonnet."""

    def __init__(
        self,
        ai: GeminiClient,
        prompt_manager: PromptManager,
        config: dict,
    ):
        self.ai = ai
        self.pm = prompt_manager
        self.threshold = (
            config.get("ai", {})
            .get("escalation", {})
            .get("confidence_threshold", 0.7)
        )
        self.max_retries = (
            config.get("ai", {}).get("escalation", {}).get("max_retries", 2)
        )

    async def resolve(
        self,
        haiku_result: dict,
        original_context: dict,
        task_type: str = "classification",
    ) -> dict:
        """
        Escalation path:
        1. Haiku returns confidence < threshold
        2. Retry Haiku once with refined prompt (add more context)
        3. If still < threshold → escalate to Sonnet
        """
        confidence = float(
            (haiku_result.get("parsed") or {}).get("confidence", 1.0)
        )

        if confidence >= self.threshold:
            return haiku_result

        # Retry Haiku with escalation context
        refined = await self._retry_haiku(haiku_result, original_context, task_type)
        refined_conf = float(
            (refined.get("parsed") or {}).get("confidence", 1.0)
        )

        if refined_conf >= self.threshold:
            return refined

        # Escalate to Sonnet
        return await self._sonnet_resolve(original_context, haiku_result, refined, task_type)

    async def _retry_haiku(
        self, haiku_result: dict, original_context: dict, task_type: str
    ) -> dict:
        variables = {
            "task_type": task_type,
            "original_context": original_context,
            "initial_confidence": (haiku_result.get("parsed") or {}).get("confidence", 0),
            "initial_result": haiku_result.get("parsed") or {},
            "uncertainty_reason": (haiku_result.get("parsed") or {}).get(
                "uncertainty_reason", "Low confidence"
            ),
        }
        system = (
            "A previous analysis was uncertain. Re-analyze with more care. "
            "Respond with ONLY valid JSON matching the original analysis schema."
        )
        prompt = self.pm.load("decisions.ambiguity_escalation", variables)
        return await self.ai.haiku(system, prompt, max_tokens=800)

    async def _sonnet_resolve(
        self,
        original_context: dict,
        haiku_result: dict,
        refined_result: dict,
        task_type: str,
    ) -> dict:
        variables = {
            "task_type": task_type,
            "original_context": original_context,
            "initial_confidence": (haiku_result.get("parsed") or {}).get("confidence", 0),
            "initial_result": haiku_result.get("parsed") or {},
            "uncertainty_reason": (refined_result.get("parsed") or {}).get(
                "uncertainty_reason", "Persistent low confidence after retry"
            ),
        }
        system = (
            "A faster model analyzed this UI element/screen but reported low confidence. "
            "You are the escalation tier — provide a definitive answer. "
            "Respond with ONLY valid JSON matching the original analysis schema."
        )
        prompt = self.pm.load("decisions.ambiguity_escalation", variables)
        return await self.ai.sonnet(system, prompt, max_tokens=1500)
