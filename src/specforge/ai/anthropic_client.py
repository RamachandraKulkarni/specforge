"""Unified Anthropic API client with concurrency control, retry, and cost tracking."""

import asyncio
import datetime
import json
import re

import anthropic
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


class BudgetExceededError(Exception):
    pass


class CostTracker:
    """Track API costs across all model tiers."""

    PRICING = {
        "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
        "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
        "claude-opus-4-6": {"input": 15.00, "output": 75.00},
    }

    def __init__(self):
        self.records: list[dict] = []
        self.total: float = 0.0

    def record(self, model: str, usage):
        pricing = self.PRICING.get(model, {"input": 3.00, "output": 15.00})
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
            if "haiku" in r["model"]:
                by_tier["decisions"] += r["cost_usd"]
            elif "sonnet" in r["model"]:
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


class AnthropicClient:
    """Unified API client for all Anthropic model calls."""

    def __init__(self, api_key: str, config: dict):
        # Explicitly set base_url to avoid ANTHROPIC_BASE_URL env var overrides
        self.client = anthropic.AsyncAnthropic(
            api_key=api_key,
            base_url="https://api.anthropic.com",
        )
        self.config = config
        self.cost_tracker = CostTracker()

        self.semaphores: dict[str, asyncio.Semaphore] = {
            "claude-haiku-4-5-20251001": asyncio.Semaphore(
                config.get("haiku_parallel", 10)
            ),
            "claude-sonnet-4-6": asyncio.Semaphore(
                config.get("sonnet_parallel", 3)
            ),
            "claude-opus-4-6": asyncio.Semaphore(1),
        }

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        retry=retry_if_exception_type(
            (anthropic.RateLimitError, anthropic.InternalServerError)
        ),
    )
    async def call(
        self,
        model: str,
        system: str,
        user_content,
        max_tokens: int = 4096,
        temperature: float = 0.1,
    ) -> dict:
        """Make an API call with concurrency control and cost tracking."""
        max_cost = self.config.get("max_cost_usd", 15.0)
        if self.cost_tracker.total >= max_cost:
            raise BudgetExceededError(
                f"Cost ${self.cost_tracker.total:.2f} exceeds limit ${max_cost}"
            )

        if isinstance(user_content, str):
            messages = [{"role": "user", "content": user_content}]
        else:
            messages = [{"role": "user", "content": user_content}]

        sem = self.semaphores.get(model, asyncio.Semaphore(1))
        async with sem:
            response = await self.client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system,
                messages=messages,
            )

        self.cost_tracker.record(model, response.usage)

        warn_cost = self.config.get("warn_cost_usd", 10.0)
        if self.cost_tracker.total >= warn_cost:
            import structlog
            structlog.get_logger().warning(
                "api_cost_warning",
                total_usd=round(self.cost_tracker.total, 2),
                threshold=warn_cost,
            )

        return self._parse(response)

    async def call_with_vision(
        self,
        model: str,
        system: str,
        text: str,
        images: list[dict],
        max_tokens: int = 4096,
        temperature: float = 0.1,
    ) -> dict:
        """Vision-enabled API call."""
        content = []
        for img in images:
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": img.get("media_type", "image/png"),
                        "data": img["base64"],
                    },
                }
            )
        content.append({"type": "text", "text": text})
        return await self.call(model, system, content, max_tokens, temperature)

    async def haiku(self, system: str, content, **kwargs) -> dict:
        return await self.call("claude-haiku-4-5-20251001", system, content, **kwargs)

    async def sonnet(self, system: str, content, **kwargs) -> dict:
        return await self.call("claude-sonnet-4-6", system, content, **kwargs)

    async def opus(self, system: str, content, **kwargs) -> dict:
        return await self.call(
            "claude-opus-4-6", system, content, max_tokens=16384, **kwargs
        )

    def _parse(self, response) -> dict:
        text = "".join(
            block.text for block in response.content if block.type == "text"
        )

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
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
            "model": response.model,
        }
