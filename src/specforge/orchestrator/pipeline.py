"""Pipeline — 3-phase parallel crawl architecture.

  Phase 1 · HAIKU  (single navigator, shallow)
            Home page → discovers top-level module entry URLs.
            max_depth=1 so it maps navigation without going deep.

  Phase 2 · HAIKU  (N navigators, parallel DFS)
            Each module gets its own Navigator instance + browser context.
            All navigators share a single SharedVisited registry so no screen is
            explored twice across parallel branches.
            Each reuses the cookie session saved by Phase 1 — no extra logins.

  Phase 3 · SONNET → OPUS
            Nav maps from all phases are merged.
            Sonnet orchestrates, analyses structure, classifies screens.
            Opus assembles the final spec document.
"""

import asyncio
import copy
import json
import os
import time
from pathlib import Path

from specforge.agents.navigator import Navigator, SharedVisited
from specforge.agents.spec_assembler import SpecAssembler
from specforge.agents.table_analyzer import TableAnalyzer
from specforge.agents.interaction_analyzer import InteractionAnalyzer
from specforge.ai.gemini_client import GeminiClient, BudgetExceededError as GeminiBudgetError
from specforge.ai.anthropic_client import AnthropicClient, BudgetExceededError as AnthropicBudgetError
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
You have received a navigation map of a web application with {screen_count} screens discovered
across {module_count} parallel crawl sessions (one per top-level module).

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
    """3-phase parallel crawl + AI assembly pipeline."""

    def __init__(self, config: dict, progress_callback=None):
        self.config = config
        self.emit = progress_callback or (lambda event, data: None)
        self.ai = None
        self.run_id: str = ""
        self.output_dir: Path = Path("./output")

    async def run(self) -> dict:
        provider = self.config.get("ai", {}).get("provider", "google")
        if provider == "google":
            api_key = os.getenv("GEMINI_API_KEY", "")
            if not api_key:
                raise ValueError("GEMINI_API_KEY is not set in .env")
            self.ai = GeminiClient(api_key, self.config.get("ai", {}))
        elif provider == "anthropic":
            api_key = os.getenv("ANTHROPIC_API_KEY", "")
            if not api_key:
                raise ValueError("ANTHROPIC_API_KEY is not set in .env")
            self.ai = AnthropicClient(api_key, self.config.get("ai", {}))
        else:
            raise ValueError(f"Unknown AI provider: {provider}")

        pm = PromptManager()

        base_url = self.config.get("target", {}).get("base_url", "").strip()
        if not base_url:
            raise ValueError(
                "No target URL provided. Paste a URL into the input bar at the top of the dashboard and click Run Pipeline."
            )

        # Parse natural-language credentials if provided
        raw_creds = self.config.get("_raw_credentials", "")
        if raw_creds and not self.config.get("_credentials", {}).get("username"):
            self.config["_credentials"] = await self._parse_credentials(raw_creds)
            self._emit_usage()

        iso    = self.config.get("target", {}).get("iso", "app")
        module = self.config.get("target", {}).get("module", "spec")
        self.run_id = f"{iso}_{module}_{_timestamp()}"
        self.output_dir = (
            Path(self.config.get("output", {}).get("directory", "./output")) / self.run_id
        )
        self.output_dir.mkdir(parents=True, exist_ok=True)

        try:
            # ──────────────────────────────────────────────────────────────────
            # PHASE 1 · HAIKU — Shallow single-navigator crawl
            #   Discovers the home page + all top-level module entry URLs.
            #   max_depth=1 so it doesn't dive into sub-pages yet.
            # ──────────────────────────────────────────────────────────────────
            self.emit("phase_start", {
                "phase": "navigation_phase1",
                "agent": "haiku-navigator",
                "message": "Phase 1 · Mapping top-level navigation structure…",
            })

            phase1_config = self._shallow_config(self.config, max_pages=25)
            nav1 = Navigator(
                self.ai, pm, phase1_config, self.output_dir,
                self.emit,
                label="phase1",
                max_depth=1,
            )
            nav_map_1 = await nav1.autonomous_crawl()
            self._save("nav_phase1.json", nav_map_1)
            self._emit_usage()

            module_entries = self._extract_module_entries(nav_map_1)
            self.emit("phase_complete", {
                "phase": "navigation_phase1",
                "count": len(nav_map_1["screens"]),
                "modules_found": [e["name"] for e in module_entries],
                "message": (
                    f"Phase 1 complete — {len(nav_map_1['screens'])} screens, "
                    f"{len(module_entries)} modules identified for deep crawl"
                ),
            })

            # ──────────────────────────────────────────────────────────────────
            # PHASE 2 · HAIKU — Parallel deep DFS, one Navigator per module
            #   Each navigator gets its own browser context + loaded session.
            #   All share a SharedVisited registry (asyncio-safe) so pages
            #   discovered by one navigator aren't re-crawled by another.
            # ──────────────────────────────────────────────────────────────────
            module_nav_maps: list[dict] = []

            if module_entries:
                self.emit("phase_start", {
                    "phase": "navigation_phase2",
                    "agent": "haiku-navigator",
                    "modules": [e["name"] for e in module_entries],
                    "message": (
                        f"Phase 2 · Deep crawling {len(module_entries)} modules in parallel — "
                        f"{', '.join(e['name'] for e in module_entries)}"
                    ),
                })

                # Seed shared state with everything Phase 1 already visited.
                shared = SharedVisited()
                shared.seed_urls(nav_map_1.get("visited_urls", []))

                async def _crawl_module(entry: dict) -> dict:
                    module_label = entry.get("name", entry["url"])

                    def module_emit(event, data):
                        self.emit(event, {**data, "module": module_label})

                    nav = Navigator(
                        self.ai, pm, self.config, self.output_dir,
                        module_emit,
                        shared_visited=shared,
                        label=module_label,
                    )
                    return await nav.autonomous_crawl(entry_url=entry["url"])

                results = await asyncio.gather(
                    *[_crawl_module(e) for e in module_entries],
                    return_exceptions=True,
                )

                for i, result in enumerate(results):
                    name = module_entries[i]["name"]
                    if isinstance(result, Exception):
                        self.emit("module_error", {
                            "module": name,
                            "error": str(result),
                            "message": f"Module '{name}' crawl failed: {result}",
                        })
                    else:
                        module_nav_maps.append(result)
                        self._save(f"nav_{name.lower().replace(' ', '_')}.json", result)
                        self.emit("module_complete", {
                            "module": name,
                            "screens": len(result.get("screens", [])),
                            "message": f"Module '{name}' — {len(result.get('screens', []))} screens discovered",
                        })

                self.emit("phase_complete", {
                    "phase": "navigation_phase2",
                    "count": sum(len(m.get("screens", [])) for m in module_nav_maps),
                    "message": (
                        f"Phase 2 complete — "
                        f"{sum(len(m.get('screens', [])) for m in module_nav_maps)} screens "
                        f"across {len(module_nav_maps)} modules"
                    ),
                })

            # ── Merge all nav maps into one unified map ─────────────────────
            nav_map = self._merge_nav_maps([nav_map_1] + module_nav_maps)
            self._save("navigation_map.json", nav_map)
            self._emit_usage()

            total_screens = len(nav_map["screens"])
            self.emit("phase_complete", {
                "phase": "navigation",
                "count": total_screens,
                "message": (
                    f"Navigation complete — {total_screens} unique screens discovered across "
                    f"{len(nav_map['stats'].get('modules_found', []))} modules"
                ),
            })

            # ──────────────────────────────────────────────────────────────────
            # LAYER 2 · SONNET — Orchestration & structure analysis
            # ──────────────────────────────────────────────────────────────────
            self.emit("phase_start", {
                "phase": "classification",
                "agent": "sonnet-orchestrator",
                "message": "Sonnet analysing app structure and classifying screens…",
            })

            orchestration = await self._sonnet_orchestrate(nav_map)
            self._save("orchestration.json", orchestration)
            self._emit_usage()

            self.emit("phase_complete", {
                "phase": "classification",
                "count": len(nav_map["screens"]),
                "message": (
                    f"Sonnet identified "
                    f"{len(orchestration.get('architecture', {}).get('modules', []))} modules"
                ),
            })

            # Table analysis (Haiku, parallel)
            self.emit("phase_start", {
                "phase": "table_analysis",
                "agent": "haiku-table-analyzer",
                "message": "Haiku analysing data tables in parallel…",
            })

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
            self.emit("phase_start", {
                "phase": "interaction_analysis",
                "agent": "haiku-interaction-analyzer",
                "message": "Haiku mapping UI interactions and workflows…",
            })

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
            self.emit("phase_start", {
                "phase": "assembly",
                "agent": "opus-assembler",
                "message": "Opus assembling final spec — this takes a few minutes…",
            })

            assembler = SpecAssembler(self.ai, pm, self.config)
            final_spec = await assembler.assemble(
                nav_map, orchestration,
                table_specs, interaction_specs,
            )

            validator = SpecValidator()
            validation = validator.validate(final_spec)
            final_spec["validation_gaps"] = validation.get("errors", [])
            final_spec["generator"]       = "specforge/2.0.0"
            final_spec["orchestration"]   = orchestration

            spec_path = self.output_dir / "final_spec.json"
            spec_path.write_text(json.dumps(final_spec, indent=2, default=str))

            summary = self.ai.cost_tracker.summary()
            self._save("cost_report.json", summary)
            self._emit_usage()

            self.emit("pipeline_complete", {
                "spec_path": str(spec_path),
                "screens_analyzed": total_screens,
                "tables_analyzed": len(table_specs),
                "interactions_analyzed": len(interaction_specs),
                "validation_gaps": len(final_spec.get("validation_gaps", [])),
                "total_api_calls": summary["total_calls"],
                "total_tokens": summary["total_input_tokens"] + summary["total_output_tokens"],
                "message": (
                    f"Spec built — {summary['total_calls']} API calls, "
                    f"{(summary['total_input_tokens'] + summary['total_output_tokens']) // 1000}K tokens"
                ),
            })

            return final_spec

        except (AnthropicBudgetError, GeminiBudgetError) as e:
            self.emit("budget_exceeded", {"error": str(e)})
            raise

    # ── Phase 1/2 helpers ────────────────────────────────────────────────────

    @staticmethod
    def _shallow_config(config: dict, max_pages: int = 25) -> dict:
        """Return a config copy that limits Phase 1 to a fast shallow crawl."""
        cfg = copy.deepcopy(config)
        cfg.setdefault("extraction", {}).setdefault("crawl", {})
        cfg["extraction"]["crawl"]["max_pages"] = max_pages
        return cfg

    @staticmethod
    def _extract_module_entries(nav_map: dict) -> list[dict]:
        """Identify top-level module landing pages from Phase 1's shallow nav map.

        We look at all depth-1 screens (direct children of the home/login page)
        that are not login screens.  Each unique URL becomes a Phase 2 entry point.
        """
        entries: list[dict] = []
        seen_urls: set[str] = set()
        for screen in nav_map.get("screens", []):
            if screen.get("depth", 0) != 1:
                continue
            if screen.get("page_type") in ("login",):
                continue
            url = screen.get("url", "")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            name = (
                screen.get("module_name")
                or screen.get("title")
                or url.split("/")[-1].replace(".htm", "").replace("_", " ").title()
            )
            entries.append({
                "name": name,
                "url": url,
                "screen_id": screen.get("id", ""),
                "page_type": screen.get("page_type", ""),
            })
        return entries

    @staticmethod
    def _merge_nav_maps(nav_maps: list[dict]) -> dict:
        """Combine nav maps from Phase 1 and all Phase 2 module navigators.

        Deduplication is by URL — first occurrence wins.
        All transitions, decision logs, and API endpoints are merged.
        """
        screens_by_url: dict[str, dict] = {}
        screens_by_id: dict[str, dict] = {}
        transitions: list[dict] = []
        decision_log: list[dict] = []
        visited_urls: set[str] = set()

        for nm in nav_maps:
            if not nm or not isinstance(nm, dict):
                continue
            for s in nm.get("screens", []):
                url = s.get("url", "")
                sid = s.get("id", "")
                if url and url not in screens_by_url:
                    screens_by_url[url] = s
                    screens_by_id[sid] = s
                elif sid and sid not in screens_by_id:
                    # Same URL already registered — skip to avoid duplicates.
                    pass
            transitions.extend(nm.get("transitions", []))
            decision_log.extend(nm.get("decision_log", []))
            visited_urls.update(nm.get("visited_urls", []))

        unique_screens = list(screens_by_url.values())
        modules = list({s.get("module_name", "") for s in unique_screens if s.get("module_name")})

        return {
            "screens": unique_screens,
            "transitions": transitions,
            "decision_log": decision_log,
            "visited_urls": list(visited_urls),
            "stats": {
                "total_screens": len(unique_screens),
                "total_transitions": len(transitions),
                "total_decisions": len(decision_log),
                "modules_found": modules,
                "phase_count": len([m for m in nav_maps if m]),
            },
        }

    # ── Sonnet orchestration ──────────────────────────────────────────────────

    async def _sonnet_orchestrate(self, nav_map: dict) -> dict:
        """Sonnet reviews the full navigation map and understands the app structure."""
        screens = nav_map.get("screens", [])
        base_url = self.config.get("target", {}).get("base_url", "")

        screen_list = "\n".join(
            f"  {s['id']} | {s['url']} | {s.get('page_type','?')} | "
            f"{s.get('module_name','?')} | {s.get('description','')}"
            for s in screens[:80]
        )

        all_tables = self._extract_tables(nav_map)
        all_endpoints = sum(len(s.get("api_endpoints", [])) for s in screens)
        modules = list({s.get("module_name") for s in screens if s.get("module_name")})

        prompt = _SONNET_ORCHESTRATE_PROMPT.format(
            screen_count=len(screens),
            module_count=nav_map.get("stats", {}).get("phase_count", 1),
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
