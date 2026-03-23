"""Agent 5: Final spec generation (Opus) — synthesis and cross-reference validation."""

import json

from specforge.ai.anthropic_client import AnthropicClient
from specforge.ai.prompt_manager import PromptManager
from specforge.ai.token_estimator import fits_in_context


class SpecAssembler:
    """Opus-powered: synthesizes all agent outputs into the final spec."""

    SYSTEM_PROMPT = (
        "You are the final assembly agent for SpecForge. You synthesize outputs from multiple "
        "specialized agents into a single, comprehensive, internally consistent JSON specification. "
        "Merge all agent outputs, resolve conflicts, fill gaps, cross-reference all IDs, "
        "and assign sequential BTN_NNN, VIEW_NNN, GRID_NNN, INT_NNN identifiers. "
        "Respond with ONLY valid JSON."
    )

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

    async def assemble(
        self,
        nav_map: dict,
        orchestration: dict,
        table_specs: list,
        interaction_specs: list,
    ) -> dict:
        import datetime

        base_variables = {
            "iso": self.iso,
            "module": self.module,
            "timestamp": datetime.datetime.now().isoformat(),
            "navigation_map": nav_map,
            "screen_classifications": classifications,
            "table_analyses": table_specs,
            "interaction_analyses": interaction_specs,
            "total_decisions": len(nav_map.get("decision_log", [])),
            "duplicates_skipped": sum(
                1 for d in nav_map.get("decision_log", []) if d.get("action") == "skip"
            ),
            "elements_skipped": sum(
                1 for d in nav_map.get("decision_log", []) if d.get("action") == "skip"
            ),
            "escalation_count": 0,
            "reference_schema": self._reference_schema(),
        }

        # Decide single-pass vs multi-pass based on token estimate
        payload_text = json.dumps(base_variables, default=str)
        if fits_in_context(self.SYSTEM_PROMPT, payload_text, context_limit=150_000):
            return await self._single_pass(base_variables)
        else:
            return await self._multi_pass(base_variables, nav_map, classifications, table_specs, interaction_specs)

    async def _single_pass(self, variables: dict) -> dict:
        prompt = self.pm.load("agents.spec_assembler", variables)
        result = await self.ai.opus(self.SYSTEM_PROMPT, prompt)
        return result.get("parsed") or {"raw": result.get("raw", ""), "error": "parse_failed"}

    async def _multi_pass(
        self,
        base_variables: dict,
        nav_map: dict,
        classifications: list,
        table_specs: list,
        interaction_specs: list,
    ) -> dict:
        # Pass 1: Navigation + Buttons
        p1_vars = {
            **base_variables,
            "button_interactions": [
                i for i in interaction_specs
                if i.get("interaction_type") in ("button_click", "form_submit")
            ],
        }
        p1_prompt = self.pm.load("agents.spec_assembler_pass1", p1_vars)
        p1_result = await self.ai.opus(self.SYSTEM_PROMPT, p1_prompt)
        p1_parsed = p1_result.get("parsed") or {}

        # Pass 2: Grids + APIs
        p2_vars = {
            **base_variables,
            "pass1_buttons_summary": [b.get("btn_index") for b in p1_parsed.get("buttons", [])],
            "grid_interactions": [
                i for i in interaction_specs
                if i.get("interaction_type") in ("column_sort", "column_filter", "row_select")
            ],
        }
        p2_prompt = self.pm.load("agents.spec_assembler_pass2", p2_vars)
        p2_result = await self.ai.opus(self.SYSTEM_PROMPT, p2_prompt)
        p2_parsed = p2_result.get("parsed") or {}

        # Pass 3: Cross-refs + Validation
        p3_vars = {
            **base_variables,
            "button_ids": [b.get("btn_index") for b in p1_parsed.get("buttons", [])],
            "view_ids": [v.get("view_id") for v in p2_parsed.get("views", [])],
            "grid_ids": [g.get("grid_id") for g in p2_parsed.get("grids", [])],
            "endpoint_ids": [e.get("endpoint_id") for e in p2_parsed.get("api_endpoints", [])],
        }
        p3_prompt = self.pm.load("agents.spec_assembler_pass3", p3_vars)
        p3_result = await self.ai.opus(self.SYSTEM_PROMPT, p3_prompt)
        p3_parsed = p3_result.get("parsed") or {}

        # Merge all three passes
        return {
            **p1_parsed,
            **p2_parsed,
            **p3_parsed,
        }

    def _reference_schema(self) -> dict:
        return {
            "iso": self.iso,
            "module": self.module,
            "version": "1.0.0",
            "navigation": {"entry_point": "", "primary_tabs": [], "tab_to_view_mapping": {}},
            "buttons": [],
            "views": [],
            "grids": [],
            "api_endpoints": [],
            "cross_references": [],
            "state_transitions": [],
            "visibility_rules": [],
            "validation_gaps": [],
        }
