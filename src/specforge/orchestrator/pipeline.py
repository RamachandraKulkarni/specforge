"""Pipeline — true 3-layer AI architecture.

  Layer 1 · HAIKU   — Navigator explores the entire UI autonomously
  Layer 2 · SONNET  — Orchestrates: understands structure, classifies screens, fills gaps
  Layer 3 · OPUS    — Assembles the final spec document
"""

import json
import os
import time
from pathlib import Path

from specforge.agents.navigator import Navigator
from specforge.agents.spec_assembler import SpecAssembler
from specforge.agents.table_analyzer import TableAnalyzer
from specforge.agents.interaction_analyzer import InteractionAnalyzer
from specforge.ai.anthropic_client import AnthropicClient, BudgetExceededError
from specforge.ai.prompt_manager import PromptManager
from specforge.assembler.validator import SpecValidator


def _timestamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


# ── Sonnet orchestration prompts ───────────────────────────────────────────────

_SONNET_ORCHESTRATE_SYSTEM = """\
You are the intelligence layer of a web UI spec generator. You receive a complete map of
a crawled web application and your job is to understand its architecture and direct the
spec assembly process.
Respond with valid JSON only."""

_SONNET_ORCHESTRATE_PROMPT = """\
You have received a navigation map of a web application with {screen_count} screens discovered.

Application overview:
  Start URL: {base_url}
  Modules found: {modules}
  Total tables: {table_count}
  Total API endpoints captured: {endpoint_count}

Screen inventory (id | url | type | module | description):
{screen_list}

Your tasks:
1. Identify the overall application structure (modules, sub-modules, workflows)
2. Classify each screen by its functional type
3. Identify the most important screens for the spec (data grids, forms, workflows)
4. Find any logical gaps (modules mentioned but not explored, common patterns missing)
5. Provide focus areas for Opus to build the spec

Respond with JSON:
{{
  "app_name": "inferred name of the application",
  "app_description": "2-3 sentence description of what this app does",
  "architecture": {{
    "modules": [
      {{
        "name": "module name",
        "screens": ["screen_id1", "screen_id2"],
        "purpose": "what this module does",
        "key_tables": ["table description"],
        "key_workflows": ["workflow description"]
      }}
    ],
    "navigation_pattern": "sidebar|tabs|top-nav|mixed",
    "auth_pattern": "cookie|token|session"
  }},
  "screen_classifications": [
    {{
      "screen_id": "abc12345",
      "functional_type": "data_grid|form|dashboard|settings|detail_view|workflow|other",
      "importance": "critical|high|medium|low",
      "key_features": ["feature 1", "feature 2"],
      "spec_notes": "what the spec should capture about this screen"
    }}
  ],
  "gaps": [
    {{
      "description": "gap description",
      "impact": "high|medium|low"
    }}
  ],
  "spec_priorities": [
    {{
      "area": "area name",
      "screen_ids": ["id1", "id2"],
      "reason": "why this is important"
    }}
  ]
}}"""


# ── Pipeline ───────────────────────────────────────────────────────────────────

class Pipeline:
    """3-layer AI pipeline: Haiku explore → Sonnet orchestrate → Opus assemble."""

    def __init__(self, config: dict, progress_callback=None):
        self.config = config
        self.emit = progress_callback or (lambda event, data: None)
        self.ai: AnthropicClient | None = None
        self.run_id: str = ""
        self.output_dir: Path = Path("./output")

    async def run(self) -> dict:
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is not set in .env")

        self.ai = AnthropicClient(api_key, self.config.get("ai", {}))
        pm = PromptManager()

        # Require a URL — must come from the dashboard input
        base_url = self.config.get("target", {}).get("base_url", "").strip()
        if not base_url:
            raise ValueError(
                "No target URL provided. Paste a URL into the input bar at the top of the dashboard and click Run Pipeline."
            )

        # Parse natural-language credentials if provided (optional)
        raw_creds = self.config.get("_raw_credentials", "")
        if raw_creds and not self.config.get("_credentials", {}).get("username"):
            self.config["_credentials"] = await self._parse_credentials(raw_creds)
            self._emit_usage()

        # Run ID from app info (no hard requirement on iso/module in config)
        iso    = self.config.get("target", {}).get("iso", "app")
        module = self.config.get("target", {}).get("module", "spec")
        self.run_id = f"{iso}_{module}_{_timestamp()}"
        self.output_dir = (
            Path(self.config.get("output", {}).get("directory", "./output")) / self.run_id
        )
        self.output_dir.mkdir(parents=True, exist_ok=True)

        try:
            # ──────────────────────────────────────────────────────────────────
            # LAYER 1 · HAIKU — Autonomous UI exploration
            # ──────────────────────────────────────────────────────────────────
            self.emit("phase_start", {"phase": "navigation", "agent": "haiku-navigator",
                                      "message": "Haiku exploring UI — mapping every screen…"})

            navigator = Navigator(self.ai, pm, self.config, self.output_dir, self.emit)
            nav_map = await navigator.autonomous_crawl()
            self._save("navigation_map.json", nav_map)
            self._emit_usage()

            self.emit("phase_complete", {
                "phase": "navigation",
                "count": len(nav_map["screens"]),
                "message": (
                    f"Haiku discovered {len(nav_map['screens'])} screens across "
                    f"{len(nav_map['stats'].get('modules_found', []))} modules"
                ),
            })

            # ──────────────────────────────────────────────────────────────────
            # LAYER 2 · SONNET — Orchestration & structure analysis
            # ──────────────────────────────────────────────────────────────────
            self.emit("phase_start", {"phase": "classification", "agent": "sonnet-orchestrator",
                                      "message": "Sonnet analysing app structure and classifying screens…"})

            orchestration = await self._sonnet_orchestrate(nav_map)
            self._save("orchestration.json", orchestration)
            self._emit_usage()

            self.emit("phase_complete", {
                "phase": "classification",
                "count": len(nav_map["screens"]),
                "message": (
                    f"Sonnet identified {len(orchestration.get('architecture', {}).get('modules', []))} modules"
                ),
            })

            # Table analysis (Haiku, parallel)
            self.emit("phase_start", {"phase": "table_analysis", "agent": "haiku-table-analyzer",
                                      "message": "Haiku analysing data tables in parallel…"})

            table_analyzer = TableAnalyzer(self.ai, pm, self.config)
            all_tables = self._extract_tables(nav_map)
            table_specs = await table_analyzer.analyze_all(all_tables)
            self._save("table_analyses.json", table_specs)
            self._emit_usage()

            self.emit("phase_complete", {
                "phase": "table_analysis",
                "count": len(table_specs),
                "message": f"Analysed {len(table_specs)} tables",
            })

            # Interaction analysis (Haiku, parallel)
            self.emit("phase_start", {"phase": "interaction_analysis", "agent": "haiku-interaction-analyzer",
                                      "message": "Haiku mapping UI interactions and workflows…"})

            interaction_analyzer = InteractionAnalyzer(self.ai, pm, self.config)
            interaction_specs = await interaction_analyzer.analyze_all(nav_map["transitions"])
            self._save("interaction_analyses.json", interaction_specs)
            self._emit_usage()

            self.emit("phase_complete", {
                "phase": "interaction_analysis",
                "count": len(interaction_specs),
                "message": f"Mapped {len(interaction_specs)} interactions",
            })

            # ──────────────────────────────────────────────────────────────────
            # LAYER 3 · OPUS — Final spec assembly
            # ──────────────────────────────────────────────────────────────────
            self.emit("phase_start", {"phase": "assembly", "agent": "opus-assembler",
                                      "message": "Opus assembling final spec — this takes a few minutes…"})

            assembler = SpecAssembler(self.ai, pm, self.config)
            final_spec = await assembler.assemble(
                nav_map, orchestration,
                table_specs, interaction_specs,
            )

            # Validate
            validator = SpecValidator()
            validation = validator.validate(final_spec)
            final_spec["validation_gaps"] = validation.get("errors", [])
            final_spec["generator"]       = "specforge/2.0.0"
            final_spec["orchestration"]   = orchestration  # embed Sonnet's analysis

            spec_path = self.output_dir / "final_spec.json"
            spec_path.write_text(json.dumps(final_spec, indent=2, default=str))

            summary = self.ai.cost_tracker.summary()
            self._save("cost_report.json", summary)
            self._emit_usage()

            self.emit("pipeline_complete", {
                "spec_path": str(spec_path),
                "screens_analyzed": len(nav_map["screens"]),
                "tables_analyzed": len(table_specs),
                "interactions_analyzed": len(interaction_specs),
                "validation_gaps": len(final_spec.get("validation_gaps", [])),
                "total_api_calls": summary["total_calls"],
                "total_tokens": summary["total_input_tokens"] + summary["total_output_tokens"],
                "message": f"Spec built — {summary['total_calls']} API calls, "
                           f"{(summary['total_input_tokens'] + summary['total_output_tokens']) // 1000}K tokens",
            })

            return final_spec

        except BudgetExceededError as e:
            self.emit("budget_exceeded", {"error": str(e)})
            raise

    # ── Sonnet orchestration ──────────────────────────────────────────────────

    async def _sonnet_orchestrate(self, nav_map: dict) -> dict:
        """Sonnet reviews the full navigation map and understands the app structure."""
        screens = nav_map.get("screens", [])
        base_url = self.config.get("target", {}).get("base_url", "")

        screen_list = "\n".join(
            f"  {s['id']} | {s['url']} | {s.get('page_type','?')} | "
            f"{s.get('module_name','?')} | {s.get('description','')}"
            for s in screens[:80]  # cap at 80 to stay within context
        )

        all_tables = self._extract_tables(nav_map)
        all_endpoints = sum(len(s.get("api_endpoints", [])) for s in screens)
        modules = list({s.get("module_name") for s in screens if s.get("module_name")})

        prompt = _SONNET_ORCHESTRATE_PROMPT.format(
            screen_count=len(screens),
            base_url=base_url,
            modules=", ".join(modules) if modules else "not yet identified",
            table_count=len(all_tables),
            endpoint_count=all_endpoints,
            screen_list=screen_list,
        )

        result = await self.ai.sonnet(
            system=_SONNET_ORCHESTRATE_SYSTEM,
            content=prompt,
            max_tokens=8192,
        )

        return result.get("parsed") or {"raw_analysis": result.get("raw", "")}

    # ── Credential parsing via Haiku ──────────────────────────────────────────

    async def _parse_credentials(self, raw: str) -> dict:
        """Haiku parses any natural-language credential input into username + password."""
        result = await self.ai.haiku(
            system=(
                "Extract a username/email and password from user-provided text. "
                "Return ONLY JSON: {\"username\": \"...\", \"password\": \"...\"}. "
                "If you cannot find a value, use an empty string."
            ),
            content=f"Extract credentials from this text:\n{raw}",
            max_tokens=128,
        )
        return result.get("parsed") or {}

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _extract_tables(self, nav_map: dict) -> list[dict]:
        tables = []
        for screen in nav_map.get("screens", []):
            for table in screen.get("tables_detected", []):
                tables.append({
                    **table,
                    "screen_id": screen["id"],
                    "screen_url": screen["url"],
                    "module": screen.get("module_name", ""),
                    "api_endpoint": next(
                        (ep["endpoint"] for ep in screen.get("api_endpoints", []) if ep.get("method") == "GET"),
                        "unknown",
                    ),
                })
        return tables

    def _emit_usage(self):
        if not self.ai:
            return
        summary = self.ai.cost_tracker.summary()

        def tokens_for(tier: str) -> int:
            return sum(
                r["input_tokens"] + r["output_tokens"]
                for r in self.ai.cost_tracker.records
                if tier in r["model"]
            )

        def calls_for(tier: str) -> int:
            return sum(1 for r in self.ai.cost_tracker.records if tier in r["model"])

        self.emit("usage_update", {
            "total_tokens": summary.get("total_input_tokens", 0) + summary.get("total_output_tokens", 0),
            "total_calls":  summary.get("total_calls", 0),
            "haiku_tokens":  tokens_for("haiku"),
            "haiku_calls":   calls_for("haiku"),
            "sonnet_tokens": tokens_for("sonnet"),
            "sonnet_calls":  calls_for("sonnet"),
            "opus_tokens":   tokens_for("opus"),
            "opus_calls":    calls_for("opus"),
        })

    def _save(self, filename: str, data):
        if self.config.get("output", {}).get("save_intermediate", True):
            path = self.output_dir / filename
            path.write_text(json.dumps(data, indent=2, default=str))
