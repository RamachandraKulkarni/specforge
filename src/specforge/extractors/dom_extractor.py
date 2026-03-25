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

            // Extract select/dropdown elements so Haiku can generate select actions.
            const selects = Array.from(
                document.querySelectorAll('select')
            ).slice(0, 20).map((el, i) => {
                const labelEl = el.id ? document.querySelector('label[for="' + el.id + '"]') : null;
                return {
                    element_id: 'sel_' + i,
                    id: el.id || '',
                    name: el.getAttribute('name') || '',
                    label: labelEl ? labelEl.innerText.trim() : '',
                    current_value: el.value || '',
                    current_text: el.options[el.selectedIndex]?.text?.trim() || '',
                    options: Array.from(el.options).map(o => ({ value: o.value, text: o.text.trim() })).slice(0, 30),
                    selector: el.id ? 'select:#' + el.id : (el.getAttribute('name') ? 'select:[name="' + el.getAttribute('name') + '"]' : 'select:select:nth-of-type(' + (i+1) + ')'),
                };
            });

            return { title, url, buttons, tabs, tables, selects, button_count: buttons.length, table_count: tables.length };
        }""")

    async def extract_table_links(self, page: Page) -> list[dict]:
        """Find every <a href> inside a <td> cell, grouped by column.

        These are row-level navigation links (e.g. clicking a portfolio name opens
        the Portfolio Editor).  Playwright extracts them deterministically — no AI needed.
        """
        return await page.evaluate("""() => {
            const groups = {};
            document.querySelectorAll('table').forEach((table, tIdx) => {
                const headers = Array.from(
                    table.querySelectorAll('thead th, thead td')
                ).map(th => th.innerText.trim());

                table.querySelectorAll('tbody tr').forEach((row, rIdx) => {
                    row.querySelectorAll('td').forEach((td, cIdx) => {
                        td.querySelectorAll('a[href]').forEach(a => {
                            const href = a.getAttribute('href') || '';
                            if (!href || href === '#' || href.startsWith('javascript:')) return;
                            const text = (a.innerText || a.textContent || '').trim();
                            const colName = headers[cIdx] || ('col_' + cIdx);
                            const key = tIdx + '_' + cIdx;
                            if (!groups[key]) {
                                groups[key] = {
                                    column_name: colName,
                                    table_index: tIdx,
                                    links: []
                                };
                            }
                            // De-duplicate by href within the group
                            if (!groups[key].links.find(l => l.href === href)) {
                                groups[key].links.push({ text, href, row: rIdx });
                            }
                        });
                    });
                });
            });
            return Object.values(groups).filter(g => g.links.length > 0);
        }""")

    async def extract_all_links(self, page: Page) -> list[dict]:
        """Extract clickable <a href> links that are NOT inside table cells.

        Covers top navigation, sidebar menus, breadcrumb links, and any standalone
        action links on the page.  Deterministic — no AI needed.
        """
        return await page.evaluate("""() => {
            const seen = new Set();
            const result = [];
            document.querySelectorAll('a[href]').forEach(a => {
                // Skip links that live inside a table cell
                if (a.closest('td, th')) return;
                const href = a.getAttribute('href') || '';
                if (!href || href === '#' || href.startsWith('javascript:') || href.startsWith('mailto:')) return;
                const text = (a.innerText || a.textContent || '').trim().substring(0, 80);
                if (!text) return;
                if (seen.has(href)) return;
                seen.add(href);
                // Classify by DOM position
                const inNav = !!a.closest('nav, [role="navigation"], .navbar, .nav, .menu, .sidebar');
                result.push({
                    text,
                    href,
                    is_nav: inNav,
                    classes: Array.from(a.classList),
                });
            });
            return result.slice(0, 60);
        }""")

    async def extract_inline_actions(self, page: Page) -> list[dict]:
        """Extract JS-triggered inline actions inside table cells (onclick, icon buttons).

        These are elements that can't be resolved to a plain href — icon buttons,
        onclick handlers, expandable row icons, etc.  The selector and outer HTML
        are returned so Playwright can click them directly.
        """
        return await page.evaluate("""() => {
            const result = [];
            document.querySelectorAll('table tbody tr').forEach((row, rIdx) => {
                row.querySelectorAll('td').forEach((td, cIdx) => {
                    // Any element with an onclick that isn't a plain link
                    td.querySelectorAll('[onclick], img[src], button, input[type="button"], input[type="image"]').forEach(el => {
                        const tag = el.tagName.toLowerCase();
                        const text = (el.innerText || el.textContent || el.getAttribute('alt') || el.getAttribute('title') || '').trim().substring(0, 40);
                        const onclick = el.getAttribute('onclick') || '';
                        if (!onclick && tag === 'img') return; // plain decorative image
                        result.push({
                            tag,
                            text,
                            onclick: onclick.substring(0, 120),
                            col_index: cIdx,
                            row_index: rIdx,
                            outer_html: el.outerHTML.substring(0, 200),
                        });
                    });
                });
            });
            return result.slice(0, 30);
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
