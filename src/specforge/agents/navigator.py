"""Agent 1: Vision-first autonomous crawler — Haiku sees and decides every navigation action."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from playwright.async_api import async_playwright

from specforge.ai.anthropic_client import AnthropicClient
from specforge.ai.image_utils import screenshot_bytes_to_vision
from specforge.ai.prompt_manager import PromptManager
from specforge.crawler.checkpoint import Checkpoint
from specforge.crawler.session_manager import SessionManager
from specforge.decisions.depth_controller import DepthController
from specforge.decisions.duplicate_detector import DuplicateDetector
from specforge.extractors.ag_grid import AGGridExtractor
from specforge.extractors.dom_extractor import DOMExtractor
from specforge.extractors.generic_table import GenericTableExtractor
from specforge.extractors.handsontable import HandsontableExtractor
from specforge.extractors.network_monitor import NetworkMonitor


# ── Prompts ────────────────────────────────────────────────────────────────────

_PAGE_SYSTEM = """\
You are an expert web UI explorer. Your mission: systematically discover every screen, module,
and workflow in a web application — like solving a maze. You receive screenshots and DOM data,
then decide what to click next to uncover new functionality.
Respond with valid JSON only — no markdown, no explanation."""

_PAGE_PROMPT = """\
Analyze this web application screenshot and DOM elements.

Current state:
  URL: {url}
  Title: {title}
  Screens discovered so far: {screen_count}
  Already-visited URLs (do NOT return actions for these): {visited_urls}

DOM elements found:
  Buttons/links ({btn_count}): {buttons}
  Tabs ({tab_count}): {tabs}
  Tables detected: {table_count}

Your task: identify every element worth clicking to discover NEW screens or functionality.

Prioritize (score 1-10):
  10 — Sidebar/left-nav module links (new module = guaranteed new screens)
  9  — Top-level nav tabs (Dashboard, FTR, Auction, etc.)
  8  — Sub-tabs or section tabs within a module
  7  — Buttons that open dialogs, panels, or new views
  6  — Expandable rows/sections with sub-content
  5  — Dropdowns revealing navigation options

Skip entirely:
  - Sort/filter/search controls
  - Pagination buttons (next/prev/page numbers)
  - Save / Submit / Delete / Cancel buttons on forms
  - Any URL already in the visited list

For selectors, give alternatives in reliability order:
  1. #id
  2. text=Exact Visible Text
  3. [role="tab"][aria-label="..."] or [aria-label="..."]
  4. .specific-class-name

Respond ONLY with this JSON:
{{
  "page_type": "login|dashboard|module|data_grid|form|dialog|settings|empty|other",
  "page_description": "one-sentence description of what this page shows",
  "module_name": "module/section name or null",
  "is_login_page": false,
  "exploration_complete": false,
  "actions": [
    {{
      "description": "Click FTR Auction tab",
      "selectors": ["text=FTR Auction", "#ftr-auction-tab", ".nav-ftr-auction"],
      "priority": 9,
      "reason": "Opens FTR Auction sub-module — likely new screens"
    }}
  ]
}}"""


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class ScreenCapture:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    url: str = ""
    title: str = ""
    depth: int = 0
    page_type: str = "unknown"
    module_name: str = ""
    description: str = ""
    screenshot_bytes: bytes = field(default_factory=bytes)
    dom_summary: dict = field(default_factory=dict)
    tables_detected: list = field(default_factory=list)
    api_endpoints: list = field(default_factory=list)
    table_count: int = 0
    button_count: int = 0


@dataclass
class Transition:
    from_screen: str
    to_screen: str
    trigger: dict
    before_state: dict = field(default_factory=dict)
    after_state: dict = field(default_factory=dict)
    network_requests: list = field(default_factory=list)


# ── Navigator ─────────────────────────────────────────────────────────────────

class Navigator:
    """Agent 1: Haiku-vision-driven autonomous crawler. No hardcoded selectors."""

    def __init__(
        self,
        ai: AnthropicClient,
        prompt_manager: PromptManager,
        config: dict,
        output_dir: Path,
        progress_callback=None,
    ):
        self.ai = ai
        self.pm = prompt_manager
        self.config = config
        self.output_dir = output_dir
        self.emit = progress_callback or (lambda event, data: None)

        crawl_cfg = config.get("extraction", {}).get("crawl", {})
        self.max_pages: int = crawl_cfg.get("max_pages", 200)
        self.nav_timeout: int = crawl_cfg.get("navigation_timeout_ms", 30000)
        self.interaction_delay: int = crawl_cfg.get("interaction_delay_ms", 500)
        self.checkpoint_interval: int = config.get("pipeline", {}).get("checkpoint_interval", 10)
        self.min_priority: int = 5  # only explore actions scored >= this

        self.screens: dict[str, ScreenCapture] = {}
        self.transitions: list[Transition] = []
        self.decision_log: list[dict] = []
        self.visited_urls: set[str] = set()

        # Extractors
        self.dom_extractor = DOMExtractor()
        self.ht_extractor = HandsontableExtractor()
        self.ag_extractor = AGGridExtractor()
        self.generic_extractor = GenericTableExtractor()

        # Decisions (depth controller still used for wrap-up)
        self.duplicate_detector = DuplicateDetector(ai, prompt_manager, config)
        self.depth_controller = DepthController(ai, prompt_manager, config)

        self.checkpoint = Checkpoint(output_dir)
        self._start_time = time.time()

    # ── Main entry ────────────────────────────────────────────────────────────

    async def autonomous_crawl(self) -> dict:
        """Vision-first maze exploration — Haiku decides every action."""
        base_url = self.config["target"]["base_url"]
        entry_path = self.config["target"].get("entry_path", "")

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={
                    "width": self.config.get("extraction", {}).get("screenshot", {}).get("width", 1920),
                    "height": self.config.get("extraction", {}).get("screenshot", {}).get("height", 1080),
                }
            )
            page = await context.new_page()

            # AI-driven auth — Haiku reads the login page, fills form itself
            session_mgr = SessionManager(self.config, self.output_dir / ".sessions", self.ai)
            await session_mgr.authenticate(page)
            self._emit_usage()

            # Navigate to entry point
            start_url = f"{base_url}{entry_path}" if entry_path else base_url
            await page.goto(start_url, timeout=self.nav_timeout)
            await page.wait_for_load_state("networkidle", timeout=self.nav_timeout)
            self.visited_urls.add(page.url)

            # Capture initial screen
            initial_screen = await self._capture_screen(page, depth=0)
            self.screens[initial_screen.id] = initial_screen
            self.emit("screen_discovered", {"screen_id": initial_screen.id, "url": initial_screen.url})

            # Ask Haiku: what's on this page and what should we explore?
            page_analysis = await self._understand_page(page, initial_screen.screenshot_bytes)
            initial_screen.page_type = page_analysis.get("page_type", "unknown")
            initial_screen.module_name = page_analysis.get("module_name") or ""
            initial_screen.description = page_analysis.get("page_description") or ""
            self._emit_usage()

            # Build priority queue: (negative_priority, counter, action_dict)
            queue: list[tuple[int, int, dict]] = []
            counter = 0
            for action in page_analysis.get("actions", []):
                if action.get("priority", 0) >= self.min_priority:
                    queue.append((
                        -action["priority"], counter,
                        {**action, "_source_url": page.url, "_depth": 1, "_source_id": initial_screen.id}
                    ))
                    counter += 1
            queue.sort()

            # ── Main exploration loop ──────────────────────────────────────
            while queue and len(self.screens) < self.max_pages:
                _, _, action = queue.pop(0)
                source_url = action.get("_source_url", "")
                source_id  = action.get("_source_id", "")
                depth      = action.get("_depth", 1)

                self.decision_log.append({
                    "action": action.get("description", ""),
                    "selectors": action.get("selectors", []),
                    "priority": action.get("priority", 0),
                    "reason": action.get("reason", ""),
                })

                # Navigate back to the source screen
                if source_url and page.url != source_url:
                    try:
                        await page.goto(source_url, timeout=self.nav_timeout)
                        await page.wait_for_load_state("networkidle", timeout=self.nav_timeout)
                    except Exception:
                        continue

                # Start network capture
                network_monitor = NetworkMonitor(page, self.config)
                await network_monitor.start_capture()
                before_url = page.url

                # Click — Haiku provided multiple selector alternatives
                clicked = await self._try_action(page, action.get("selectors", []))
                if not clicked:
                    await network_monitor.stop_capture()
                    continue

                await asyncio.sleep(self.interaction_delay / 1000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=self.nav_timeout)
                except Exception:
                    pass

                network_requests = await network_monitor.stop_capture()
                after_url = page.url

                # Skip if URL didn't change and we've seen it
                if after_url in self.visited_urls and after_url == before_url:
                    try:
                        await page.go_back(timeout=self.nav_timeout)
                        await page.wait_for_load_state("networkidle", timeout=self.nav_timeout)
                    except Exception:
                        pass
                    continue

                self.visited_urls.add(after_url)

                # Capture this new screen
                new_screen = await self._capture_screen(page, depth=depth)
                new_screen.api_endpoints = network_monitor.get_api_endpoints()

                # Haiku duplicate check
                dup_result = await self.duplicate_detector.is_duplicate(
                    vars(new_screen), [vars(s) for s in self.screens.values()]
                )
                if dup_result.is_duplicate:
                    self.emit("duplicate_skipped", {"url": new_screen.url, "duplicate_of": dup_result.duplicate_of})
                    try:
                        await page.go_back(timeout=self.nav_timeout)
                        await page.wait_for_load_state("networkidle", timeout=self.nav_timeout)
                    except Exception:
                        pass
                    continue

                # Register new screen
                self.screens[new_screen.id] = new_screen
                self.transitions.append(Transition(
                    from_screen=source_id,
                    to_screen=new_screen.id,
                    trigger={"description": action.get("description"), "selectors": action.get("selectors")},
                    before_state={"url": before_url},
                    after_state={"url": after_url},
                    network_requests=network_requests,
                ))
                self.emit("screen_discovered", {
                    "screen_id": new_screen.id,
                    "url": new_screen.url,
                    "depth": depth,
                    "module": new_screen.module_name,
                })

                # Ask Haiku: what can we explore from this new screen?
                new_analysis = await self._understand_page(page, new_screen.screenshot_bytes)
                new_screen.page_type   = new_analysis.get("page_type", "unknown")
                new_screen.module_name = new_analysis.get("module_name") or ""
                new_screen.description = new_analysis.get("page_description") or ""
                self._emit_usage()

                for act in new_analysis.get("actions", []):
                    if act.get("priority", 0) >= self.min_priority:
                        queue.append((
                            -act["priority"], counter,
                            {**act, "_source_url": after_url, "_depth": depth + 1, "_source_id": new_screen.id}
                        ))
                        counter += 1
                queue.sort()

                # Depth / wrap-up check every 5 screens
                if len(self.screens) % 5 == 0:
                    depth_decision = await self.depth_controller.should_continue_exploring({
                        "current_depth": depth,
                        "total_screens": len(self.screens),
                        "analyzed_screens": len(self.screens),
                        "recent_new_tables": sum(s.table_count for s in list(self.screens.values())[-5:]),
                        "recent_new_buttons": sum(s.button_count for s in list(self.screens.values())[-5:]),
                        "recent_new_endpoints": sum(len(s.api_endpoints) for s in list(self.screens.values())[-5:]),
                        "cost_so_far": self.ai.cost_tracker.total,
                        "time_elapsed": (time.time() - self._start_time) / 60,
                        "queue_size": len(queue),
                    })
                    if depth_decision.action == "wrap_up":
                        self.emit("depth_wrap_up", {"reason": depth_decision.reason})
                        break
                    elif depth_decision.action == "skip_branch":
                        queue = [(p, c, e) for p, c, e in queue if e.get("_depth", 0) <= depth]

                # Checkpoint
                if len(self.screens) % self.checkpoint_interval == 0:
                    self.checkpoint.save({
                        "screens": {k: {f: v for f, v in vars(s).items() if f != "screenshot_bytes"}
                                    for k, s in self.screens.items()},
                        "transition_count": len(self.transitions),
                    })

            await browser.close()

        return self.build_navigation_map()

    # ── Haiku: understand what's on the page ─────────────────────────────────

    async def _understand_page(self, page, screenshot_bytes: bytes) -> dict:
        """Haiku vision call — sees the page, returns typed actions to explore."""
        img = screenshot_bytes_to_vision(
            screenshot_bytes,
            max_size_kb=self.config.get("extraction", {}).get("screenshot", {}).get("max_size_kb", 500),
        )
        dom = await self.dom_extractor.extract_summary(page)

        prompt = _PAGE_PROMPT.format(
            url=page.url,
            title=dom.get("title", ""),
            screen_count=len(self.screens),
            visited_urls=json.dumps(list(self.visited_urls)[-30:]),  # last 30 to stay within token limit
            btn_count=len(dom.get("buttons", [])),
            buttons=json.dumps(dom.get("buttons", [])[:25], ensure_ascii=False),
            tab_count=len(dom.get("tabs", [])),
            tabs=json.dumps(dom.get("tabs", [])[:20], ensure_ascii=False),
            table_count=dom.get("table_count", 0),
        )

        result = await self.ai.call_with_vision(
            model="claude-haiku-4-5-20251001",
            system=_PAGE_SYSTEM,
            text=prompt,
            images=[img],
            max_tokens=2048,
        )

        analysis = result.get("parsed") or {}

        # Log the decision
        self.decision_log.append({
            "type": "page_understanding",
            "url": page.url,
            "page_type": analysis.get("page_type"),
            "module": analysis.get("module_name"),
            "actions_found": len(analysis.get("actions", [])),
        })

        return analysis

    # ── Click with fallback selectors ─────────────────────────────────────────

    async def _try_action(self, page, selectors: list[str]) -> bool:
        """Try each selector alternative until one works."""
        for selector in selectors:
            try:
                if selector.startswith("text="):
                    text = selector[5:].strip()
                    loc = page.get_by_text(text, exact=False).first
                    await loc.click(timeout=5000)
                elif selector.startswith("role="):
                    # role=button[name="Login"] or role=tab[name="FTR"]
                    parts = selector[5:].split("[", 1)
                    role = parts[0].strip()
                    name = None
                    if len(parts) > 1:
                        name_part = parts[1].rstrip("]")
                        if name_part.startswith('name="') and name_part.endswith('"'):
                            name = name_part[6:-1]
                    if name:
                        await page.get_by_role(role, name=name).first.click(timeout=5000)
                    else:
                        await page.get_by_role(role).first.click(timeout=5000)
                else:
                    await page.click(selector, timeout=5000)
                return True
            except Exception:
                continue
        return False

    # ── Screen capture ────────────────────────────────────────────────────────

    async def _capture_screen(self, page, depth: int) -> ScreenCapture:
        screenshot_bytes = await page.screenshot(full_page=False)
        dom_summary = await self.dom_extractor.extract_summary(page)

        tables = (
            await self.ht_extractor.extract_all(page)
            + await self.ag_extractor.extract_all(page)
            + await self.generic_extractor.extract_all(page)
        )

        sc = ScreenCapture(
            url=page.url,
            title=await page.title(),
            depth=depth,
            screenshot_bytes=screenshot_bytes,
            dom_summary=dom_summary,
            tables_detected=tables,
            table_count=dom_summary.get("table_count", 0),
            button_count=dom_summary.get("button_count", 0),
        )

        if self.config.get("output", {}).get("save_screenshots", True):
            ss_dir = self.output_dir / "screenshots"
            ss_dir.mkdir(parents=True, exist_ok=True)
            (ss_dir / f"{sc.id}.png").write_bytes(screenshot_bytes)

        return sc

    # ── Usage telemetry ───────────────────────────────────────────────────────

    def _emit_usage(self):
        """Emit current API call / token counts to the SSE stream."""
        summary = self.ai.cost_tracker.summary()
        by_model = summary.get("by_model", {})

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

    # ── Build navigation map ──────────────────────────────────────────────────

    def build_navigation_map(self) -> dict:
        return {
            "screens": [
                {
                    "id": sc.id,
                    "url": sc.url,
                    "title": sc.title,
                    "depth": sc.depth,
                    "page_type": sc.page_type,
                    "module_name": sc.module_name,
                    "description": sc.description,
                    "table_count": sc.table_count,
                    "button_count": sc.button_count,
                    "tables_detected": sc.tables_detected,
                    "dom_summary": sc.dom_summary,
                    "api_endpoints": sc.api_endpoints,
                }
                for sc in self.screens.values()
            ],
            "transitions": [
                {
                    "from_screen": t.from_screen,
                    "to_screen": t.to_screen,
                    "trigger": t.trigger,
                    "before_state": t.before_state,
                    "after_state": t.after_state,
                    "network_requests": t.network_requests[:10],
                }
                for t in self.transitions
            ],
            "decision_log": self.decision_log,
            "stats": {
                "total_screens": len(self.screens),
                "total_transitions": len(self.transitions),
                "total_decisions": len(self.decision_log),
                "elapsed_minutes": round((time.time() - self._start_time) / 60, 1),
                "modules_found": list({s.module_name for s in self.screens.values() if s.module_name}),
            },
        }
