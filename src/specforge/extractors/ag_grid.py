"""AG Grid extraction via Playwright."""

from playwright.async_api import Page

_AG_SCRIPT = """(selector) => {
    const root = document.querySelector(selector);
    if (!root) return null;

    const headers = Array.from(root.querySelectorAll('.ag-header-cell')).map((el, i) => ({
        index: i,
        text: el.querySelector('.ag-header-cell-text')?.innerText?.trim() || '',
        col_id: el.getAttribute('col-id') || '',
        sortable: !!el.querySelector('.ag-sort-indicator-icon'),
        has_filter: !!el.querySelector('.ag-floating-filter-input'),
        resizable: !!el.querySelector('.ag-header-cell-resize'),
        width: el.offsetWidth,
        classes: Array.from(el.classList)
    }));

    const rows = Array.from(root.querySelectorAll('.ag-row')).slice(0, 5).map((row, ri) =>
        Array.from(row.querySelectorAll('.ag-cell')).map((cell, ci) => ({
            row: ri,
            col: ci,
            col_id: cell.getAttribute('col-id') || '',
            value: cell.innerText?.trim().substring(0, 200) || '',
            editable: cell.getAttribute('aria-readonly') !== 'true',
            has_checkbox: !!cell.querySelector('input[type=checkbox]'),
            classes: Array.from(cell.classList)
        }))
    );

    return {
        framework: 'ag-grid',
        headers,
        sample_rows: rows,
        total_rows: root.querySelectorAll('.ag-row').length,
        total_cols: headers.length,
        has_row_selection: !!root.querySelector('.ag-selection-checkbox'),
        pagination: !!root.querySelector('.ag-paging-panel')
    };
}"""


class AGGridExtractor:
    """Extract metadata from AG Grid instances."""

    async def extract(self, page: Page, grid_selector: str) -> dict | None:
        return await page.evaluate(_AG_SCRIPT, grid_selector)

    async def extract_all(self, page: Page) -> list[dict]:
        selectors: list[str] = await page.evaluate("""() =>
            Array.from(document.querySelectorAll('.ag-root-wrapper'))
                 .map((el, i) => el.id ? '#' + el.id : '.ag-root-wrapper:nth-of-type(' + (i+1) + ')')
        """)
        results = []
        for sel in selectors:
            data = await self.extract(page, sel)
            if data:
                data["selector"] = sel
                results.append(data)
        return results
