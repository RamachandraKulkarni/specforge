"""Capture and categorize network requests during interactions."""

import time
from playwright.async_api import Page


class NetworkMonitor:
    """Capture and categorize XHR/fetch network requests during interactions."""

    def __init__(self, page: Page, config: dict | None = None):
        self.page = page
        self.requests: list[dict] = []
        self.capturing = False
        self._ignore_patterns: list[str] = (
            (config or {})
            .get("extraction", {})
            .get("network", {})
            .get("ignore_patterns", ["/static/", "/assets/", ".css", ".js", ".woff"])
        )

    async def start_capture(self):
        self.capturing = True
        self.requests = []

        async def on_request(request):
            if not self.capturing:
                return
            if request.resource_type not in ("xhr", "fetch"):
                return
            url = request.url
            if any(pat in url for pat in self._ignore_patterns):
                return
            self.requests.append(
                {
                    "url": url,
                    "method": request.method,
                    "post_data": request.post_data,
                    "resource_type": request.resource_type,
                    "timestamp": time.time(),
                }
            )

        async def on_response(response):
            if not self.capturing:
                return
            if response.request.resource_type not in ("xhr", "fetch"):
                return
            for req in reversed(self.requests):
                if req["url"] == response.url and "response" not in req:
                    try:
                        body = await response.json()
                    except Exception:
                        try:
                            body = await response.text()
                        except Exception:
                            body = ""
                    req["response"] = {
                        "status": response.status,
                        "headers": dict(response.headers),
                        "body_preview": str(body)[:2000],
                        "body_full": body,
                    }
                    break

        self.page.on("request", on_request)
        self.page.on("response", on_response)

    async def stop_capture(self) -> list[dict]:
        self.capturing = False
        return list(self.requests)

    def get_api_endpoints(self) -> list[dict]:
        """Extract unique API endpoints from captured requests."""
        seen: set[str] = set()
        endpoints: list[dict] = []
        for req in self.requests:
            base_url = req["url"].split("?")[0]
            key = f"{req['method']}:{base_url}"
            if key not in seen:
                seen.add(key)
                endpoints.append(
                    {
                        "endpoint": base_url,
                        "method": req["method"],
                        "sample_params": req["url"].split("?")[1]
                        if "?" in req["url"]
                        else None,
                        "sample_response": req.get("response", {}).get("body_preview"),
                    }
                )
        return endpoints
