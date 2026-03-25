"""Auth, cookies, and session persistence — AI-driven, zero hardcoded selectors."""

import json
from pathlib import Path

from playwright.async_api import Page

from specforge.ai.image_utils import screenshot_bytes_to_vision


# ── Prompts ────────────────────────────────────────────────────────────────────

_ANALYZE_SYSTEM = """\
You are a web automation expert. You analyze screenshots and DOM data from web pages
to identify login form elements and return precise CSS selectors.
Respond with valid JSON only — no markdown, no explanation."""

_ANALYZE_PROMPT = """\
Analyze this page screenshot and the interactive elements listed below.

Determine:
1. Is this a login / sign-in page?
2. Is the user already authenticated (dashboard, app content visible)?
3. If it is a login page, what are the CSS selectors for:
   - The username / email input
   - The password input
   - The submit / sign-in button
4. What CSS selector would appear on the page AFTER a successful login?

Interactive elements detected:
{elements}

Rules for selectors (prefer in order):
  - #id  →  most reliable
  - [name="x"]  →  second best
  - input[type="password"]  →  for password fields
  - input[type="email"] or input[type="text"]  →  for username/email
  - button[type="submit"] or the most prominent button  →  for submit
  - If multiple options exist, pick the most specific

Respond ONLY with this JSON:
{{
  "is_login_page": true,
  "already_authenticated": false,
  "username_selector": "#username",
  "password_selector": "#password",
  "submit_selector": "#login-btn",
  "success_selector": "nav.main-nav",
  "confidence": 0.95,
  "notes": "brief observation"
}}"""

_VERIFY_SYSTEM = """\
You are a web automation expert verifying whether a login attempt succeeded.
Respond with valid JSON only — no markdown, no explanation."""

_VERIFY_PROMPT = """\
A login form was just submitted. Analyze this screenshot.

Determine:
1. Did login succeed? (look for: dashboard, sidebar, nav menus, user avatar, app content)
2. Is there a visible error? (wrong password, account locked, captcha, etc.)
3. Is there a 2FA / MFA challenge requiring a code?
4. What CSS selector on this page confirms authenticated state?

Respond ONLY with this JSON:
{{
  "login_success": true,
  "has_error": false,
  "error_message": null,
  "has_mfa": false,
  "success_selector": ".main-sidebar",
  "notes": "brief observation"
}}"""


# ── Helper: extract all visible form elements via JS ──────────────────────────

_EXTRACT_JS = """\
() => {
  const visible = el => {
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };

  const bestSelector = el => {
    if (el.id) return '#' + el.id;
    if (el.name) return el.tagName.toLowerCase() + '[name="' + el.name + '"]';
    if (el.type) return el.tagName.toLowerCase() + '[type="' + el.type + '"]';
    const cls = Array.from(el.classList).find(c => c.length > 2 && !c.match(/^(col|row|d-|m-|p-|w-|h-)/));
    if (cls) return el.tagName.toLowerCase() + '.' + cls;
    return el.tagName.toLowerCase();
  };

  const labelFor = el => {
    if (el.id) {
      const lbl = document.querySelector('label[for="' + el.id + '"]');
      if (lbl) return lbl.innerText.trim().substring(0, 60);
    }
    return el.getAttribute('aria-label') || el.getAttribute('placeholder') || null;
  };

  const inputs = Array.from(document.querySelectorAll('input, textarea, select'))
    .filter(visible)
    .map(el => ({
      tag: el.tagName.toLowerCase(),
      type: el.type || el.tagName.toLowerCase(),
      id: el.id || null,
      name: el.name || null,
      placeholder: el.placeholder || null,
      label: labelFor(el),
      selector: bestSelector(el),
      autocomplete: el.getAttribute('autocomplete') || null
    }));

  const buttons = Array.from(
    document.querySelectorAll('button, input[type="submit"], input[type="button"], [role="button"]')
  )
    .filter(visible)
    .map(el => ({
      tag: el.tagName.toLowerCase(),
      type: el.type || 'button',
      id: el.id || null,
      text: (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().substring(0, 80),
      selector: bestSelector(el),
      classes: Array.from(el.classList).slice(0, 4)
    }));

  return { inputs, buttons };
}
"""


# ── SessionManager ─────────────────────────────────────────────────────────────

class SessionManager:
    """Manage authentication using AI vision — no hardcoded selectors needed."""

    def __init__(self, config: dict, session_dir: Path | None = None, ai=None):
        self.config = config
        self.ai = ai  # GeminiClient — optional, falls back to config selectors
        self.auth_config = config.get("target", {}).get("auth", {})
        self.session_dir = session_dir or Path("./output/.sessions")
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self._session_file = self.session_dir / "session.json"

    async def authenticate(self, page: Page) -> bool:
        """Authenticate. Uses AI vision if client available, config selectors otherwise."""
        # Try reusing an existing saved session first
        if await self._load_session(page):
            return True

        base_url   = self.config.get("target", {}).get("base_url", "").rstrip("/")
        login_path = self.auth_config.get("login_url", "").strip()

        # Navigate to login URL if specified, otherwise use the base URL directly
        target = f"{base_url}{login_path}" if login_path else base_url
        await page.goto(target)
        await page.wait_for_load_state("networkidle")

        if self.ai:
            return await self._ai_authenticate(page)
        else:
            return await self._config_authenticate(page)

    # ── AI-driven auth ────────────────────────────────────────────────────────

    async def _ai_authenticate(self, page: Page) -> bool:
        """Use Haiku vision to detect the login form and fill it."""
        creds = self.config.get("_credentials", {})
        username = creds.get("username", "")
        password = creds.get("password", "")

        # No credentials provided — check if the page needs auth at all
        if not username or not password:
            screenshot = await page.screenshot()
            img = screenshot_bytes_to_vision(screenshot, max_size_kb=300)
            check = await self.ai.call_with_vision(
                model=self.config["ai"]["models"]["decision"],
                system="You analyze web pages. Respond with JSON only.",
                text='Is this page a login/sign-in wall that blocks access without credentials? Respond: {"requires_login": true/false}',
                images=[img],
                max_tokens=64,
            )
            parsed = check.get("parsed") or {}
            if not parsed.get("requires_login", False):
                # Already accessible — no login needed, proceed
                return True
            # Page requires login but no credentials given — skip auth, proceed anyway
            # The crawler will explore whatever is publicly accessible
            return True

        # Step 1: Screenshot + DOM elements
        screenshot = await page.screenshot()
        img = screenshot_bytes_to_vision(screenshot, max_size_kb=500)
        elements = await page.evaluate(_EXTRACT_JS)

        # Step 2: Ask Haiku to identify the form
        prompt = _ANALYZE_PROMPT.format(elements=json.dumps(elements, indent=2))
        result = await self.ai.call_with_vision(
            model=self.config["ai"]["models"]["decision"],
            system=_ANALYZE_SYSTEM,
            text=prompt,
            images=[img],
            max_tokens=512,
        )

        analysis = result.get("parsed")
        if not analysis:
            raise RuntimeError(
                f"Haiku could not parse the login page. Raw response: {result.get('raw', '')[:300]}"
            )

        # Already logged in
        if analysis.get("already_authenticated"):
            await self._save_session(page)
            return True

        if not analysis.get("is_login_page"):
            raise RuntimeError(
                f"Haiku says this is not a login page (confidence={analysis.get('confidence')}). "
                f"Notes: {analysis.get('notes')}. Check your login_url in config.yaml."
            )

        confidence = analysis.get("confidence", 0)
        if confidence < 0.5:
            raise RuntimeError(
                f"Haiku has low confidence ({confidence}) identifying the login form. "
                f"Notes: {analysis.get('notes')}"
            )

        # Step 3: Fill the form using AI-identified selectors
        u_sel = analysis.get("username_selector")
        p_sel = analysis.get("password_selector")
        s_sel = analysis.get("submit_selector")

        if not all([u_sel, p_sel, s_sel]):
            raise RuntimeError(
                f"Haiku could not identify all form fields. Got: {analysis}"
            )

        try:
            await page.fill(u_sel, username)
            await page.fill(p_sel, password)
            await page.click(s_sel)
            await page.wait_for_load_state("networkidle", timeout=20000)
        except Exception as e:
            raise RuntimeError(
                f"Failed to interact with login form using selectors "
                f"(u={u_sel}, p={p_sel}, submit={s_sel}): {e}"
            ) from e

        # Step 4: Verify login success with another Haiku call
        screenshot_after = await page.screenshot()
        img_after = screenshot_bytes_to_vision(screenshot_after, max_size_kb=500)

        verify_result = await self.ai.call_with_vision(
            model=self.config["ai"]["models"]["decision"],
            system=_VERIFY_SYSTEM,
            text=_VERIFY_PROMPT,
            images=[img_after],
            max_tokens=256,
        )

        verify = verify_result.get("parsed")

        if verify and verify.get("has_mfa"):
            raise RuntimeError(
                "MFA/2FA challenge detected. Automated MFA is not yet supported. "
                "Log in manually, export cookies, and place them in "
                f"{self._session_file}"
            )

        if verify and verify.get("has_error"):
            raise RuntimeError(
                f"Login failed: {verify.get('error_message', 'Unknown error')}. "
                "Check SF_USERNAME / SF_PASSWORD in your .env file."
            )

        # Save session on success
        await self._save_session(page)
        return True

    # ── Config-based fallback auth ────────────────────────────────────────────

    async def _config_authenticate(self, page: Page) -> bool:
        """Fallback: use hardcoded selectors from config.yaml (legacy behavior)."""
        creds = self.auth_config.get("credentials", {})
        u_sel = creds.get("username_field", "#username")
        p_sel = creds.get("password_field", "#password")
        s_sel = creds.get("submit_button", "#login-btn")
        success = creds.get("success_indicator", ".dashboard-loaded")

        config_creds = self.config.get("_credentials", {})
        username = config_creds.get("username", "")
        password = config_creds.get("password", "")

        if username:
            await page.fill(u_sel, username)
        if password:
            await page.fill(p_sel, password)
        await page.click(s_sel)

        try:
            await page.wait_for_selector(success, timeout=30000)
        except Exception:
            return False

        await self._save_session(page)
        return True

    # ── Session persistence ───────────────────────────────────────────────────

    async def _save_session(self, page: Page):
        cookies = await page.context.cookies()
        self._session_file.write_text(json.dumps(cookies, indent=2))

    async def _load_session(self, page: Page) -> bool:
        if not self._session_file.exists():
            return False
        try:
            cookies = json.loads(self._session_file.read_text())
            await page.context.add_cookies(cookies)
            return True
        except Exception:
            return False

    def clear_session(self):
        if self._session_file.exists():
            self._session_file.unlink()
