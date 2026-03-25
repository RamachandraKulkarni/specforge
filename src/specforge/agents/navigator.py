"""Agent 1: Vision-first autonomous crawler — Haiku sees and decides every navigation action."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from playwright.async_api import async_playwright

from specforge.ai.gemini_client import GeminiClient
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


# ── Shared state for parallel module navigators ────────────────────────────────

class SharedVisited:
    """Async-safe URL + DOM-state registry shared across parallel Navigator instances.

    Phase 2 navigators each run their own DFS on one module, but all register
    discovered URLs and DOM state fingerprints here so no two navigators duplicate
    work on the same screen.
    """

    def __init__(self):
        self._lock = asyncio.Lock()
        self._urls: set[str] = set()
        self._states: set[str] = set()

    async def add_url(self, url: str) -> bool:
        """Register url. Returns True if it was NEW (not previously seen)."""
        async with self._lock:
            if url in self._urls:
                return False
            self._urls.add(url)
            return True

    async def has_url(self, url: str) -> bool:
        async with self._lock:
            return url in self._urls

    async def add_state(self, state: str) -> bool:
        """Register DOM-state fingerprint. Returns True if NEW."""
        async with self._lock:
            if state in self._states:
                return False
            self._states.add(state)
            return True

    def snapshot_urls(self) -> set[str]:
        """Non-locking snapshot of all known URLs — eventual consistency is fine
        for DOM-action filtering (avoids N lock acquisitions in a tight loop)."""
        return set(self._urls)

    def seed_urls(self, urls: list[str]):
        """Synchronously pre-populate from Phase 1 results (called before tasks start)."""
        self._urls.update(urls)


# ── Prompts ────────────────────────────────────────────────────────────────────

_PAGE_SYSTEM = """\
You are a web UI analysis expert working as part of a spec-generation pipeline.
Playwright has already extracted all plain links, tabs, and known buttons from the DOM for you.
Your job is NOT to re-discover those — they are pre-listed below.
Your job IS to:
  1. Classify the page (page_type, module_name, page_description).
  2. Identify interactions Playwright CANNOT see from the DOM alone:
     - Icon buttons / image buttons that trigger JS popups or inline editors (e.g. "Bid Curve" icon)
     - onclick-only actions with no href (right-click menus, row expand icons, modal triggers)
     - Context-sensitive dropdowns that appear only after another action
     - Any element whose purpose is only clear from the visual screenshot
  3. Suggest select-dropdown actions for fields whose options should be individually explored.
  4. Assign priority scores so the crawler focuses on the most valuable interactions first.
Respond with valid JSON only — no markdown, no explanation."""

_PAGE_PROMPT = """\
Current page state:
  URL: {url}
  Title: {title}
  Exploration Depth: {depth}
  Screens discovered so far: {screen_count}
  Already-visited URLs (skip these): {visited_urls}

== Pre-extracted by Playwright (DO NOT repeat these in your output) ==
  {dom_actions_count} actions already queued:
  {dom_actions_summary}

== Raw DOM elements for your reference ==
  Buttons/links ({btn_count}): {buttons}
  Tabs ({tab_count}): {tabs}
  Select/dropdowns ({sel_count}): {selects}
  Tables detected: {table_count}

== Your task ==
Look at the screenshot carefully. Identify interactions that Playwright's DOM extraction MISSED:
  - Icon/image buttons in table cells that open inline editors or popups (e.g. pencil icon, bid-curve icon)
  - onclick= handlers on table rows or cells that trigger modals
  - Dropdown menus that only appear after hovering or clicking a parent element
  - Any "Add New", "Edit", "Detail" button that navigates to a sub-screen
  - Select dropdowns worth exploring — list each meaningful option as a SEPARATE action

CRITICAL — SPA awareness:
  URL may NOT change on click. Each distinct UI state is a different screen.
  Depth >= 1: do NOT suggest top-level nav items — focus on page-level interactions only.

Selector format (reliability order):
  1. #id   2. text=Exact Text   3. [aria-label="..."]   4. .class-name
  For selects: "select:#id"  or  "select:[name='field']" with a "select_value" field.

Respond ONLY with this JSON:
{{
  "page_type": "login|dashboard|module|data_grid|form|dialog|settings|empty|other",
  "page_description": "one-sentence description of what this screen does",
  "module_name": "module or section name",
  "exploration_complete": false,
  "actions": [
    {{
      "description": "Click bid-curve icon on row 1 to open Bid Curve Editor popup",
      "selectors": ["td img.bid-curve-icon", "td:nth-child(2) img", "text=🔑"],
      "action_type": "click",
      "priority": 8,
      "reason": "Icon button in Bid Curve column — triggers a popup editor with MW/Price grid"
    }},
    {{
      "description": "Select Period Jun_27 from Period dropdown",
      "selectors": ["select:#period", "select:[name='period']"],
      "action_type": "select",
      "select_value": "Jun_27",
      "priority": 7,
      "reason": "Different period loads a different data set worth capturing"
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
        ai: GeminiClient,
        prompt_manager: PromptManager,
        config: dict,
        output_dir: Path,
        progress_callback=None,
        shared_visited: SharedVisited | None = None,
        label: str = "",
        max_depth: int | None = None,
    ):
        self.ai = ai
        self.pm = prompt_manager
        self.config = config
        self.output_dir = output_dir
        self.emit = progress_callback or (lambda event, data: None)
        self._shared = shared_visited   # cross-navigator URL/state dedup (Phase 2)
        self._label = label             # e.g. "Nominations" — used in log messages
        self._max_depth = max_depth     # hard depth cap (None = use DepthController)

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
        self.visited_states: set[str] = set()  # DOM-content fingerprints — catches SPA same-URL re-visits

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

    async def autonomous_crawl(self, entry_url: str | None = None) -> dict:
        """Vision-first maze exploration — Haiku decides every action.

        Args:
            entry_url: When set (Phase 2), skip home and start crawling from this
                       module URL directly. SessionManager loads the saved cookie
                       session so no re-login is needed.
        """
        base_url = self.config["target"]["base_url"]
        entry_path = self.config["target"].get("entry_path", "")

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context(
                ignore_https_errors=True,
                viewport={
                    "width": self.config.get("extraction", {}).get("screenshot", {}).get("width", 1920),
                    "height": self.config.get("extraction", {}).get("screenshot", {}).get("height", 1080),
                }
            )
            page = await context.new_page()

            # Background loop to send live frames to frontend
            async def _preview_loop():
                while not page.is_closed():
                    try:
                        await self._emit_live_preview(page)
                    except Exception:
                        pass
                    await asyncio.sleep(0.5)
            
            preview_task = asyncio.create_task(_preview_loop())

            # Auth — loads saved session (Phase 2) or does full login (Phase 1).
            # SessionManager checks for a saved cookie file first; if valid, skips login.
            session_mgr = SessionManager(self.config, self.output_dir / ".sessions", self.ai)
            await session_mgr.authenticate(page)
            self._emit_usage()

            # Navigate to entry point.
            # Phase 1: home/base URL.  Phase 2: specific module URL passed in.
            start_url = entry_url or (f"{base_url}{entry_path}" if entry_path else base_url)
            await page.goto(start_url, timeout=self.nav_timeout)
            await page.wait_for_load_state("networkidle", timeout=self.nav_timeout)
            self.visited_urls.add(page.url)
            if self._shared:
                await self._shared.add_url(page.url)

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

            # Fingerprint the initial UI state so child actions can replay back to it.
            initial_state_key = await self._compute_dom_state_key(page)
            self.visited_states.add(initial_state_key)
            if self._shared:
                await self._shared.add_state(initial_state_key)

            # Build priority queue: (negative_priority, counter, action_dict)
            queue: list[tuple[int, int, dict]] = []
            counter = 0
            for action in page_analysis.get("actions", []):
                if action.get("priority", 0) >= self.min_priority:
                    queue.append((
                        -action["priority"], counter,
                        {
                            **action,
                            "_source_url": page.url,
                            "_source_state": initial_state_key,
                            "_action_path": [],   # root: no replay needed
                            "_depth": 1,
                            "_source_id": initial_screen.id,
                        }
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

                # Restore the exact UI state where this action was discovered.
                # For SPAs the URL doesn't change — we replay the action path instead of goto().
                if not await self._ensure_source_state(page, action):
                    continue

                # Start network capture
                network_monitor = NetworkMonitor(page, self.config)
                await network_monitor.start_capture()
                before_url = page.url

                # Execute action — Haiku provided multiple selector alternatives
                clicked = await self._try_action(
                    page,
                    action.get("selectors", []),
                    action_type=action.get("action_type", "click"),
                    select_value=action.get("select_value"),
                )
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

                # Compute the new UI state fingerprint (works for SPAs where URL doesn't change).
                after_state_key = await self._compute_dom_state_key(page)

                # Skip if we've already explored this exact UI state AND nothing loaded via XHR.
                # Check both local set (fast) AND shared set (cross-navigator dedup for Phase 2).
                state_seen_locally = after_state_key in self.visited_states
                state_seen_shared  = self._shared and not await self._shared.add_state(after_state_key)
                if (state_seen_locally or state_seen_shared) and not network_requests:
                    continue

                # Register in local + shared sets.
                self.visited_states.add(after_state_key)
                self.visited_urls.add(after_url)
                if self._shared:
                    await self._shared.add_url(after_url)

                # Capture this new screen
                new_screen = await self._capture_screen(page, depth=depth)
                new_screen.api_endpoints = network_monitor.get_api_endpoints()

                # Haiku duplicate check
                dup_result = await self.duplicate_detector.is_duplicate(
                    vars(new_screen), [vars(s) for s in self.screens.values()]
                )
                if dup_result.is_duplicate:
                    self.emit("duplicate_skipped", {"url": new_screen.url, "duplicate_of": dup_result.duplicate_of})
                    # Only go_back when the URL actually changed (hard navigation).
                    # For SPA pages (URL unchanged), going back would break state;
                    # _ensure_source_state will restore it via action-path replay.
                    if after_url != before_url:
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
                new_analysis = await self._understand_page(page, new_screen.screenshot_bytes, depth=depth + 1)
                new_screen.page_type   = new_analysis.get("page_type", "unknown")
                new_screen.module_name = new_analysis.get("module_name") or ""
                new_screen.description = new_analysis.get("page_description") or ""
                self._emit_usage()

                # Build the replay path so child actions can restore this SPA state.
                # Only extend the path when the URL did NOT change (true SPA transition).
                # For hard navigations (URL changed), goto(source_url) is sufficient —
                # adding the nav click would cause _ensure_source_state to replay it while
                # already on the target page, re-triggering the navigation and causing a loop.
                parent_path = action.get("_action_path", [])
                if after_url == before_url:
                    new_action_path = parent_path + [{
                        "selectors": action.get("selectors", []),
                        "action_type": action.get("action_type", "click"),
                        "select_value": action.get("select_value"),
                        "description": action.get("description", ""),
                    }]
                else:
                    # Hard navigation — URL changed, so the source_url alone restores state.
                    new_action_path = []

                # Queue child actions unless we've hit a hard depth cap (Phase 1 shallow crawl).
                next_depth = depth + 1
                if self._max_depth is None or depth < self._max_depth:
                    for act in new_analysis.get("actions", []):
                        if act.get("priority", 0) >= self.min_priority:
                            queue.append((
                                -act["priority"], counter,
                                {
                                    **act,
                                    "_source_url": after_url,
                                    "_source_state": after_state_key,
                                    "_action_path": new_action_path,
                                    "_depth": next_depth,
                                    "_source_id": new_screen.id,
                                }
                            ))
                            counter += 1
                    queue.sort()

                # Depth / wrap-up check every 5 screens (skipped when hard cap active).
                if self._max_depth is None and len(self.screens) % 5 == 0:
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

            preview_task.cancel()
            await browser.close()

        return self.build_navigation_map()

    # ── SPA-safe state fingerprinting & navigation ────────────────────────────

    async def _compute_dom_state_key(self, page) -> str:
        """Content-based UI state fingerprint.

        Uses actual button/tab text + table count — NOT just the URL — so that
        same-URL SPA states (e.g. nomination page before vs. after clicking Go)
        are treated as distinct states.
        """
        try:
            dom = await self.dom_extractor.extract_summary(page)
            url = page.url
            btn_texts = "|".join((b.get("text") or "")[:20] for b in dom.get("buttons", [])[:15])
            tab_texts = "|".join((t.get("text") or "")[:20] for t in dom.get("tabs", [])[:10])
            table_count = str(dom.get("table_count", 0))
            state_str = f"{url}::{btn_texts}::{tab_texts}::{table_count}"
            return hashlib.md5(state_str.encode()).hexdigest()
        except Exception:
            return hashlib.md5(page.url.encode()).hexdigest()

    async def _ensure_source_state(self, page, action: dict) -> bool:
        """Return to the exact UI state where an action was discovered.

        For SPAs where the URL never changes, we cannot just page.goto() back —
        that reloads a blank page losing all state (dropdown selections, loaded grids).
        Instead we navigate to the base URL then REPLAY the chain of clicks that
        originally produced the source state.
        """
        source_url = action.get("_source_url", "")
        source_state = action.get("_source_state")
        action_path = action.get("_action_path", [])

        # Already in the right state — nothing to do.
        if source_state:
            current_state = await self._compute_dom_state_key(page)
            if current_state == source_state:
                return True

        # Navigate to the source URL if we're on a different one.
        if source_url and page.url != source_url:
            try:
                await page.goto(source_url, timeout=self.nav_timeout)
                await page.wait_for_load_state("networkidle", timeout=self.nav_timeout)
            except Exception:
                return False

        # Replay the interaction chain to restore SPA state.
        for step in action_path:
            selectors = step.get("selectors", [])
            action_type = step.get("action_type", "click")
            select_value = step.get("select_value")
            clicked = await self._try_action(page, selectors, action_type=action_type, select_value=select_value)
            if not clicked:
                # Path replay failed — proceed from current state anyway
                break
            await asyncio.sleep(self.interaction_delay / 1000)
            try:
                await page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass

        return True

    # ── DOM-first extraction (free — no AI credits) ───────────────────────────

    async def _extract_dom_actions(self, page, depth: int = 0) -> list[dict]:
        """Extract all actionable elements from the live DOM without any AI call.

        Playwright reads the real DOM so row-level <a href> links, inactive tabs,
        and known button types are captured deterministically and cheaply.
        Results are returned in the same action-dict format the queue expects.
        """
        dom          = await self.dom_extractor.extract_summary(page)
        table_links  = await self.dom_extractor.extract_table_links(page)
        page_links   = await self.dom_extractor.extract_all_links(page)
        base          = self.config["target"]["base_url"].rstrip("/")
        actions: list[dict] = []

        # One non-locking snapshot of shared URLs for efficient filtering below.
        shared_urls = self._shared.snapshot_urls() if self._shared else set()

        # ── 1. Row-level table links (e.g. portfolio name → editor page) ─────
        #    Each distinct href in a column is a new screen to discover.
        #    We sample up to 3 per column to avoid exploding the queue on large lists.
        for group in table_links:
            col = group.get("column_name", "")
            sampled = group.get("links", [])[:3]
            for link in sampled:
                href = link.get("href", "")
                if not href:
                    continue
                full_url = href if href.startswith("http") else f"{base}{href}"
                if full_url in self.visited_urls or full_url in shared_urls:
                    continue
                text = link.get("text", col)
                actions.append({
                    "description": f"Open row link '{text}' in column '{col}'",
                    "selectors": [f"a[href='{href}']", f"text={text}"],
                    "action_type": "click",
                    "priority": 8,
                    "reason": f"Clickable row value in '{col}' column → opens detail/editor at {href}",
                    "_target_url": full_url,
                })

        # ── 2. Navigation / breadcrumb links (top-level only at depth 0) ─────
        for link in page_links:
            href = link.get("href", "")
            if not href:
                continue
            full_url = href if href.startswith("http") else f"{base}{href}"
            if full_url in self.visited_urls or full_url in shared_urls:
                continue
            text = link.get("text", "").strip()
            if not text:
                continue
            # At depth>0 only follow nav links — not deep content links —
            # to avoid re-entering top-level navigation from inside a module.
            priority = 9 if link.get("is_nav") else (7 if depth == 0 else 4)
            if priority < self.min_priority:
                continue
            actions.append({
                "description": f"Navigate to: {text}",
                "selectors": [f"a[href='{href}']", f"text={text}"],
                "action_type": "click",
                "priority": priority,
                "reason": "Navigational link found in DOM",
                "_target_url": full_url,
            })

        # ── 3. Inactive tabs (sub-tabs within a module) ────────────────────
        for tab in dom.get("tabs", []):
            if tab.get("active"):
                continue
            text = (tab.get("text") or "").strip()
            if not text:
                continue
            actions.append({
                "description": f"Switch to tab: {text}",
                "selectors": [f"text={text}", f"[role='tab'][aria-label='{text}']"],
                "action_type": "click",
                "priority": 7,
                "reason": f"Inactive tab '{text}' — may reveal distinct data view",
            })

        # ── 4. Known data-loading buttons (Go / Search / Run / Filter) ───────
        _LOAD_WORDS = {"go", "search", "run", "filter", "apply", "load", "find", "refresh"}
        seen_btns: set[str] = set()
        for btn in dom.get("buttons", []):
            label = (btn.get("text") or btn.get("aria_label") or "").strip()
            if label.lower() in _LOAD_WORDS and label not in seen_btns:
                seen_btns.add(label)
                actions.append({
                    "description": f"Click '{label}' to load data",
                    "selectors": [
                        f"input[value='{label}']",
                        f"text={label}",
                        f"#{btn.get('id', '__none__')}",
                        "button[type='submit']",
                    ],
                    "action_type": "click",
                    "priority": 9,
                    "reason": "Data-loading button — will trigger XHR and populate grid",
                })

        return actions

    def _heuristic_page_type(self, dom: dict) -> str:
        """Classify page type from DOM structure alone — used when Haiku is skipped."""
        tables  = dom.get("table_count", 0)
        selects = len(dom.get("selects", []))
        tabs    = len(dom.get("tabs", []))
        btns    = dom.get("button_count", 0)
        if tables > 0 and selects > 0:
            return "data_grid"
        if tables > 0:
            return "data_grid"
        if tabs > 1:
            return "module"
        if btns > 4:
            return "form"
        return "other"

    def _heuristic_module_name(self, dom: dict, url: str) -> str:
        """Infer module name from page title or URL path — used when Haiku is skipped."""
        title = dom.get("title", "")
        if title:
            # Strip trailing app name after " - " or " | "
            for sep in (" - ", " | ", " — "):
                if sep in title:
                    return title.split(sep)[0].strip()
            return title.strip()[:40]
        # Fall back to last meaningful URL path segment
        parts = [p for p in url.rstrip("/").split("/") if p and "." not in p]
        return parts[-1].replace("-", " ").replace("_", " ").title() if parts else "Unknown"

    async def _needs_ai_analysis(self, page, dom: dict, dom_actions: list[dict], depth: int) -> bool:
        """Decide whether to make a Haiku vision call after DOM extraction.

        Haiku IS needed when:
        - No DOM actions were found (page relies on JS rendering / no plain hrefs)
        - An open dialog / modal is detected (popup interactions need vision)
        - Depth >= 2 (complex nested states need contextual understanding)
        - There are inline onclick table actions the DOM extractor flagged

        Haiku can be SKIPPED when:
        - DOM found ≥ 3 definitive actions (links with real hrefs)
        - Page is a plain list/grid with clear navigation structure
        """
        if not dom_actions:
            return True  # DOM found nothing — AI must look at the screenshot

        if depth >= 2:
            return True  # Deep states need contextual interpretation

        # Check for an open modal / dialog
        try:
            has_dialog = await page.evaluate("""() =>
                !!document.querySelector(
                  '[role="dialog"]:not([style*="display: none"]), '
                + '.ui-dialog:not([style*="display: none"]), '
                + '.modal.show, .popup:not([style*="display: none"])'
                )
            """)
            if has_dialog:
                return True
        except Exception:
            pass

        # Count actions that have definitive target URLs (plain hrefs)
        definitive = sum(1 for a in dom_actions if a.get("_target_url"))
        if definitive >= 3:
            return False  # Enough clear targets — skip AI call

        return True  # Uncertain — let Haiku supplement

    # ── Haiku: interpret the page (DOM context already supplied) ─────────────

    async def _understand_page(self, page, screenshot_bytes: bytes, depth: int = 0) -> dict:
        """DOM-first, AI-optional page analysis.

        Phase 1 (free): Playwright extracts all links, table row links, tabs, buttons.
        Phase 2 (conditional): Haiku vision call — only when DOM is ambiguous or deep.
          When called, Haiku receives the pre-extracted DOM actions so it focuses on
          INTERPRETATION (context, priority, JS-triggered interactions) not re-discovery.
        """
        dom         = await self.dom_extractor.extract_summary(page)
        dom_actions = await self._extract_dom_actions(page, depth=depth)

        if not await self._needs_ai_analysis(page, dom, dom_actions, depth):
            # ── DOM-only path (no Haiku call) ────────────────────────────────
            page_type   = self._heuristic_page_type(dom)
            module_name = self._heuristic_module_name(dom, page.url)
            self.decision_log.append({
                "type": "dom_extraction",
                "url": page.url,
                "page_type": page_type,
                "module": module_name,
                "actions_found": len(dom_actions),
                "ai_used": False,
            })
            return {
                "page_type": page_type,
                "page_description": f"{page_type} — extracted by DOM without AI",
                "module_name": module_name,
                "exploration_complete": False,
                "actions": dom_actions,
            }

        # ── Haiku vision call (AI-supplement path) ───────────────────────────
        img = screenshot_bytes_to_vision(
            screenshot_bytes,
            max_size_kb=self.config.get("extraction", {}).get("screenshot", {}).get("max_size_kb", 500),
        )

        prompt = _PAGE_PROMPT.format(
            url=page.url,
            title=dom.get("title", ""),
            depth=depth,
            screen_count=len(self.screens),
            visited_urls=json.dumps(list(self.visited_urls)[-30:]),
            btn_count=len(dom.get("buttons", [])),
            buttons=json.dumps(dom.get("buttons", [])[:25], ensure_ascii=False),
            tab_count=len(dom.get("tabs", [])),
            tabs=json.dumps(dom.get("tabs", [])[:20], ensure_ascii=False),
            sel_count=len(dom.get("selects", [])),
            selects=json.dumps(dom.get("selects", [])[:15], ensure_ascii=False),
            table_count=dom.get("table_count", 0),
            dom_actions_count=len(dom_actions),
            dom_actions_summary=json.dumps(
                [{"desc": a["description"], "priority": a.get("priority", 0)} for a in dom_actions[:12]],
                ensure_ascii=False,
            ),
        )

        result = await self.ai.call_with_vision(
            model=self.config["ai"]["models"]["decision"],
            system=_PAGE_SYSTEM,
            text=prompt,
            images=[img],
            max_tokens=2048,
        )

        analysis = result.get("parsed") or {}
        ai_actions = analysis.get("actions", [])

        # Merge: DOM actions first (definitive), then unique AI actions (inferred).
        dom_descs = {a["description"].lower() for a in dom_actions}
        unique_ai = [a for a in ai_actions if a.get("description", "").lower() not in dom_descs]
        analysis["actions"] = dom_actions + unique_ai
        analysis["_ai_used"] = True

        self.decision_log.append({
            "type": "page_understanding",
            "url": page.url,
            "page_type": analysis.get("page_type"),
            "module": analysis.get("module_name"),
            "dom_actions": len(dom_actions),
            "ai_actions": len(unique_ai),
            "actions_found": len(analysis["actions"]),
            "ai_used": True,
        })

        return analysis

    # ── Click with fallback selectors ─────────────────────────────────────────

    async def _emit_live_preview(self, page):
        """Emit a low-res screenshot to SSE for the live preview pane."""
        try:
            buf = await page.screenshot(type="jpeg", quality=40)
            import base64
            b64 = base64.b64encode(buf).decode('ascii')
            self.emit("preview_frame", {"frame": f"data:image/jpeg;base64,{b64}"})
        except Exception:
            pass

    async def _try_action(
        self,
        page,
        selectors: list[str],
        action_type: str = "click",
        select_value: str | None = None,
    ) -> bool:
        """Try each selector alternative until one works.

        Supports:
          - click  (default)
          - select  — selectors prefixed with "select:" or action_type=="select"
        """
        for selector in selectors:
            try:
                # ── SELECT / DROPDOWN ──────────────────────────────────────
                is_select = action_type == "select" or selector.startswith("select:")
                if is_select:
                    css = selector.removeprefix("select:").strip()
                    value = select_value or ""
                    if not value:
                        continue  # no value to select — skip
                    await page.select_option(css, value, timeout=5000)
                    return True

                # ── CLICK ──────────────────────────────────────────────────
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
            "visited_urls": list(self.visited_urls),  # used to seed Phase 2 shared state
            "stats": {
                "total_screens": len(self.screens),
                "total_transitions": len(self.transitions),
                "total_decisions": len(self.decision_log),
                "elapsed_minutes": round((time.time() - self._start_time) / 60, 1),
                "modules_found": list({s.module_name for s in self.screens.values() if s.module_name}),
                "label": self._label or "phase1",
            },
        }
