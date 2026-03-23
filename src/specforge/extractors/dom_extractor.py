"""Playwright DOM/accessibility tree extraction."""

from playwright.async_api import Page


class DOMExtractor:
    """Extract DOM structure, accessibility tree, and page metadata."""

    async def extract_summary(self, page: Page) -> dict:
        """Lightweight DOM summary for AI prompts."""
        return await page.evaluate("""() => {
            const title = document.title;
            const url = location.href;

            const buttons = Array.from(
                document.querySelectorAll('button, [role="button"], input[type="submit"], a.btn')
            ).slice(0, 50).map((el, i) => ({
                element_id: 'btn_' + i,
                tag: el.tagName.toLowerCase(),
                text: el.innerText?.trim().substring(0, 80) || '',
                aria_label: el.getAttribute('aria-label') || '',
                classes: Array.from(el.classList),
                href: el.getAttribute('href') || '',
                input_type: el.getAttribute('type') || '',
                disabled: el.disabled || el.getAttribute('aria-disabled') === 'true',
                position: (() => {
                    const r = el.getBoundingClientRect();
                    return { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) };
                })(),
                parent_context: el.closest('[class]')?.className?.substring(0, 60) || ''
            }));

            const tabs = Array.from(
                document.querySelectorAll('[role="tab"], .nav-tab, .tab-link, li.active > a')
            ).slice(0, 20).map((el, i) => ({
                element_id: 'tab_' + i,
                text: el.innerText?.trim().substring(0, 80) || '',
                active: el.getAttribute('aria-selected') === 'true' || el.classList.contains('active'),
                href: el.getAttribute('href') || ''
            }));

            const tables = Array.from(
                document.querySelectorAll('.handsontable, .ag-root, table.dataTable, table')
            ).slice(0, 10).map((el, i) => ({
                table_index: i,
                framework: el.classList.contains('handsontable') ? 'handsontable'
                    : el.classList.contains('ag-root') ? 'ag-grid'
                    : el.classList.contains('dataTable') ? 'datatables' : 'generic',
                selector: el.id ? '#' + el.id : el.className?.split(' ')[0] || 'table',
                row_count: el.querySelectorAll('tbody tr').length,
                col_count: el.querySelectorAll('thead th').length
            }));

            return { title, url, buttons, tabs, tables, button_count: buttons.length, table_count: tables.length };
        }""")

    async def extract_accessibility_tree(self, page: Page) -> dict:
        """Extract accessibility tree for the page."""
        snapshot = await page.accessibility.snapshot(interesting_only=True)
        return snapshot or {}

    async def get_page_html(self, page: Page, max_chars: int = 50000) -> str:
        html = await page.content()
        return html[:max_chars]

    async def get_element_rect(self, page: Page, selector: str) -> dict | None:
        try:
            rect = await page.eval_on_selector(
                selector,
                "el => { const r = el.getBoundingClientRect(); "
                "return {x: r.x, y: r.y, w: r.width, h: r.height}; }"
            )
            return rect
        except Exception:
            return None
