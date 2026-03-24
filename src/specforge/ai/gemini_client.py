"""Unified Gemini API client with concurrency control, retry, and cost tracking."""
import asyncio
import datetime
import json
import re

import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted, InternalServerError

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

class BudgetExceededError(Exception):
    pass

class UsageProxy:
    def __init__(self, input_tokens, output_tokens):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens

class CostTracker:
    """Track API costs across all model tiers."""
    PRICING = {
        "gemini-2.5-flash": {"input": 0.075, "output": 0.30},
        "gemini-2.5-pro": {"input": 1.25, "output": 5.00},
        "gemini-3.1-flash-lite-preview": {"input": 0.075, "output": 0.30},
    }

    def __init__(self):
        self.records: list[dict] = []
        self.total: float = 0.0

    def record(self, model: str, usage):
        pricing = self.PRICING.get(model, {"input": 0.075, "output": 0.30})
        cost = (
            usage.input_tokens * pricing["input"]
            + usage.output_tokens * pricing["output"]
        ) / 1_000_000
        self.total += cost
        self.records.append(
            {
                "model": model,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "cost_usd": round(cost, 6),
                "timestamp": datetime.datetime.now().isoformat(),
            }
        )

    def summary(self) -> dict:
        by_model: dict[str, float] = {}
        by_tier = {"decisions": 0.0, "analysis": 0.0, "assembly": 0.0}
        for r in self.records:
            by_model[r["model"]] = by_model.get(r["model"], 0.0) + r["cost_usd"]
            if "flash" in r["model"]:
                by_tier["decisions"] += r["cost_usd"]
            elif "pro" in r["model"]:
                by_tier["analysis"] += r["cost_usd"]
            else:
                by_tier["assembly"] += r["cost_usd"]
        return {
            "total_usd": round(self.total, 2),
            "by_model": {k: round(v, 4) for k, v in by_model.items()},
            "by_tier": {k: round(v, 4) for k, v in by_tier.items()},
            "total_calls": len(self.records),
            "total_input_tokens": sum(r["input_tokens"] for r in self.records),
            "total_output_tokens": sum(r["output_tokens"] for r in self.records),
        }

class GeminiClient:
    """Unified API client for all Gemini model calls."""

    def __init__(self, api_key: str, config: dict):
        genai.configure(api_key=api_key)
        self.config = config
        self.cost_tracker = CostTracker()

        self.semaphores: dict[str, asyncio.Semaphore] = {
            "gemini-2.5-flash": asyncio.Semaphore(
                config.get("flash_parallel", 10)
            ),
            "gemini-2.5-pro": asyncio.Semaphore(
                config.get("pro_parallel", 3)
            ),
        }

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        retry=retry_if_exception_type(
            (ResourceExhausted, InternalServerError)
        ),
    )
    async def call(
        self,
        model: str,
        system: str,
        user_content,
        max_tokens: int = 8192,
        temperature: float = 0.1,
    ) -> dict:
        """Make an API call with concurrency control and cost tracking."""
        max_cost = self.config.get("max_cost_usd", 15.0)
        if self.cost_tracker.total >= max_cost:
            raise BudgetExceededError(
                f"Cost ${self.cost_tracker.total:.2f} exceeds limit ${max_cost}"
            )

        generative_model = genai.GenerativeModel(
            model_name=model,
            system_instruction=system
        )
        
        sem = self.semaphores.get(model, asyncio.Semaphore(1))
        async with sem:
            # We must use content wrapper 
            response = await generative_model.generate_content_async(
                contents=user_content,
                generation_config=genai.GenerationConfig(
                    max_output_tokens=max_tokens,
                    temperature=temperature,
                )
            )

        usage = UsageProxy(
            input_tokens=response.usage_metadata.prompt_token_count,
            output_tokens=response.usage_metadata.candidates_token_count
        )
        self.cost_tracker.record(model, usage)

        warn_cost = self.config.get("warn_cost_usd", 10.0)
        if self.cost_tracker.total >= warn_cost:
            import structlog
            structlog.get_logger().warning(
                "api_cost_warning",
                total_usd=round(self.cost_tracker.total, 2),
                threshold=warn_cost,
            )

        return self._parse(response.text, model, usage)

    async def call_with_vision(
        self,
        model: str,
        system: str,
        text: str,
        images: list[dict],
        max_tokens: int = 8192,
        temperature: float = 0.1,
    ) -> dict:
        """Vision-enabled API call."""
        content = []
        for img in images:
            content.append({
                "mime_type": img.get("media_type", "image/png"),
                "data": img["base64"]
            })
        content.append(text)
        return await self.call(model, system, content, max_tokens, temperature)

    async def haiku(self, system: str, content, **kwargs) -> dict:
        return await self.call("gemini-2.5-flash", system, content, **kwargs)

    async def sonnet(self, system: str, content, **kwargs) -> dict:
        return await self.call("gemini-2.5-pro", system, content, **kwargs)

    async def opus(self, system: str, content, **kwargs) -> dict:
        return await self.call("gemini-2.5-pro", system, content, **kwargs)

    def _parse(self, text: str, model: str, usage: UsageProxy) -> dict:
        parsed = None
        try:
            json_match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group(1))
            elif text.strip().startswith("{") or text.strip().startswith("["):
                parsed = json.loads(text.strip())
        except json.JSONDecodeError:
            pass

        return {
            "raw": text,
            "parsed": parsed,
            "usage": {
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
            },
            "model": model,
        }
