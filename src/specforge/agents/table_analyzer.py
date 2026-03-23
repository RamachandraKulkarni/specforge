"""Agent 3: Column/grid deep analysis (Haiku + sub-agents) with parallel enrichment."""

import asyncio

from specforge.ai.anthropic_client import AnthropicClient
from specforge.ai.image_utils import screenshot_bytes_to_vision
from specforge.ai.prompt_manager import PromptManager
from specforge.decisions.ambiguity_resolver import AmbiguityResolver


class TableAnalyzer:
    """Multi-pass table analysis with four Haiku sub-agents."""

    SYSTEM_PROMPT = (
        "You produce column-level specifications for data grids in web applications. "
        "You understand Handsontable, AG Grid, DataTables, and generic HTML tables. "
        "For energy market grids, common column types include: MW, price ($/MW), dates, "
        "status enums, IDs, path names, and boolean flags. "
        "Respond with ONLY valid JSON. No markdown, no explanation."
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
        self.resolver = AmbiguityResolver(ai, prompt_manager, config)

    async def analyze_all(self, tables: list[dict]) -> list[dict]:
        tasks = [self._analyze_one(table) for table in tables]
        return await asyncio.gather(*tasks)

    async def _analyze_one(self, table_data: dict) -> dict:
        variables = {
            "iso": self.iso,
            "module": self.module,
            "screen_id": table_data.get("screen_id", ""),
            "table_id": table_data.get("table_id", table_data.get("selector", "")),
            "view_flow_type": table_data.get("view_flow_type", "unknown"),
            "grid_framework": table_data.get("framework", "generic"),
            "column_dom_metadata": table_data.get("headers", []),
            "sample_row_count": len(table_data.get("sample_rows", [])),
            "sample_cell_data": table_data.get("sample_rows", []),
            "api_endpoint": table_data.get("api_endpoint", "unknown"),
            "api_method": table_data.get("api_method", "GET"),
            "api_response_fields": table_data.get("api_response_fields", []),
            "has_frozen_columns": table_data.get("has_frozen_columns", False),
            "frozen_col_count": table_data.get("frozen_col_count", 0),
            "has_row_headers": table_data.get("has_row_headers", False),
            "has_column_resize": table_data.get("has_column_resize", False),
            "nested_headers": table_data.get("nested_headers", False),
            "header_levels": table_data.get("header_levels", 1),
            "total_rows": table_data.get("total_rows", 0),
            "total_columns": table_data.get("total_cols", 0),
            "is_scrollable": table_data.get("is_scrollable", False),
            "chunk_note": "",
        }

        prompt = self.pm.load("agents.table_analyzer", variables)

        screenshot_bytes = table_data.get("screenshot_bytes")
        if screenshot_bytes:
            img = screenshot_bytes_to_vision(screenshot_bytes)
            result = await self.ai.call_with_vision(
                "claude-haiku-4-5-20251001", self.SYSTEM_PROMPT, prompt, [img], max_tokens=2000
            )
        else:
            result = await self.ai.haiku(self.SYSTEM_PROMPT, prompt, max_tokens=2000)

        columns = (result.get("parsed") or {}).get("columns", [])

        # Pass 2: sub-agents in parallel
        enrichments = await asyncio.gather(
            self._header_behavior_analysis(columns, table_data),
            self._filter_type_detection(columns, table_data),
            self._validation_rule_inference(columns, table_data),
            self._api_field_mapping(columns, table_data),
        )

        merged = self._merge_enrichments(columns, enrichments)

        # Pass 4: deep-dive on low-confidence columns
        for col in merged:
            if float(col.get("confidence", 1.0)) < 0.7:
                deep_result = await self.resolver.resolve(
                    {"parsed": col}, {"column": col, "table": table_data}, "column_analysis"
                )
                col.update(deep_result.get("parsed") or {})

        parsed = result.get("parsed") or {}
        parsed["columns"] = merged
        parsed["table_id"] = table_data.get("table_id", table_data.get("selector", ""))
        return parsed

    async def _header_behavior_analysis(self, columns: list, table_data: dict) -> dict:
        variables = {
            "grid_framework": table_data.get("framework", "generic"),
            "columns_with_dom": columns,
            "sort_indicators": [c for c in (table_data.get("headers") or []) if c.get("has_sort_indicator")],
            "filter_elements": [c for c in (table_data.get("headers") or []) if c.get("has_filter")],
        }
        system = "You analyze column header behaviors in data grids. Respond with ONLY valid JSON."
        prompt = self.pm.load("sub_agents.header_behavior_analyzer", variables)
        result = await self.ai.haiku(system, prompt, max_tokens=800)
        return {"header_behavior": (result.get("parsed") or {}).get("columns", [])}

    async def _filter_type_detection(self, columns: list, table_data: dict) -> dict:
        variables = {
            "filter_dom": [h for h in (table_data.get("headers") or []) if h.get("has_filter")],
            "sample_values": {
                str(i): [row[i]["value"] if i < len(row) else "" for row in (table_data.get("sample_rows") or [])]
                for i in range(len(columns))
            },
        }
        system = "You identify filter types for data grid columns. Respond with ONLY valid JSON."
        prompt = self.pm.load("sub_agents.filter_type_detector", variables)
        result = await self.ai.haiku(system, prompt, max_tokens=600)
        return {"filter_types": (result.get("parsed") or {}).get("filters", [])}

    async def _validation_rule_inference(self, columns: list, table_data: dict) -> dict:
        variables = {
            "column_specs": columns,
            "sample_values": table_data.get("sample_rows", [])[:5],
            "editor_types": [c.get("editor") for c in columns],
        }
        system = "You infer data validation rules for grid columns. Respond with ONLY valid JSON."
        prompt = self.pm.load("sub_agents.validation_rule_inferrer", variables)
        result = await self.ai.haiku(system, prompt, max_tokens=600)
        return {"validations": (result.get("parsed") or {}).get("validations", [])}

    async def _api_field_mapping(self, columns: list, table_data: dict) -> dict:
        network_response = table_data.get("network_response", {})
        variables = {
            "api_fields": list(network_response.keys()) if isinstance(network_response, dict) else [],
            "column_headers": [c.get("header_label", "") for c in columns],
            "api_sample_values": network_response if isinstance(network_response, dict) else {},
            "cell_sample_values": {
                c.get("header_label", f"col_{i}"): [
                    row[i]["value"] if i < len(row) else ""
                    for row in (table_data.get("sample_rows") or [])
                ]
                for i, c in enumerate(columns)
            },
        }
        system = "You match API response field names to table column headers. Respond with ONLY a valid JSON array."
        prompt = self.pm.load("sub_agents.api_field_mapper", variables)
        result = await self.ai.haiku(system, prompt, max_tokens=600)
        mappings = result.get("parsed") or []
        return {"api_mappings": mappings if isinstance(mappings, list) else []}

    def _merge_enrichments(self, columns: list, enrichments: tuple) -> list:
        header_map = {c.get("col_key"): c for c in enrichments[0].get("header_behavior", [])}
        filter_map = {c.get("col_key"): c for c in enrichments[1].get("filter_types", [])}
        validation_map = {c.get("col_key"): c for c in enrichments[2].get("validations", [])}
        api_map = {c.get("header"): c for c in enrichments[3].get("api_mappings", [])}

        merged = []
        for col in columns:
            key = col.get("col_key", "")
            header_label = col.get("header_label", "")

            enriched = dict(col)
            if key in header_map:
                hb = header_map[key]
                enriched.setdefault("sortable", hb.get("sort_behavior", {}).get("enabled", col.get("sortable", False)))
                enriched.setdefault("filterable", hb.get("filter_behavior", {}).get("enabled", col.get("filterable", False)))
            if key in filter_map:
                enriched["filter_type"] = filter_map[key].get("filter_type", col.get("filter_type", "none"))
            if key in validation_map:
                enriched["validation"] = validation_map[key].get("constraints", col.get("validation", {}))
                enriched["validation"]["required"] = validation_map[key].get("required", False)
            if header_label in api_map:
                enriched["source_api_field"] = api_map[header_label].get("api_field")

            merged.append(enriched)
        return merged
