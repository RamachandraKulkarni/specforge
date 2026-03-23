"""Extract deep metadata from Handsontable grids via Playwright."""

from playwright.async_api import Page

_EXTRACTION_SCRIPT = """(selector) => {
    const container = document.querySelector(selector)
        ?.closest('[data-handsontable]')
        || document.querySelector(selector)?.closest('.handsontable');

    if (!container) return null;

    const headers = Array.from(
        container.querySelectorAll('.ht_master thead th')
    ).map((th, idx) => ({
        index: idx,
        text: th.innerText.trim(),
        width: th.offsetWidth,
        has_sort_indicator: !!th.querySelector('.ascending, .descending, [class*=sort]'),
        sort_direction: th.querySelector('.ascending') ? 'asc'
            : th.querySelector('.descending') ? 'desc' : null,
        has_filter: !!th.querySelector('[class*=filter], select, input'),
        filter_type: th.querySelector('select') ? 'dropdown'
            : th.querySelector('input[type=text]') ? 'text'
            : th.querySelector('input[type=number]') ? 'numeric' : null,
        classes: Array.from(th.classList),
        colspan: th.colSpan || 1,
        is_grouped_header: (th.colSpan || 1) > 1
    }));

    const rows = Array.from(
        container.querySelectorAll('.ht_master tbody tr')
    ).slice(0, 5).map(tr =>
        Array.from(tr.querySelectorAll('td')).map((td, idx) => ({
            index: idx,
            value: td.innerText.trim().substring(0, 200),
            has_input: !!td.querySelector('input'),
            input_type: td.querySelector('input')?.type || null,
            has_select: !!td.querySelector('select'),
            select_options: td.querySelector('select')
                ? Array.from(td.querySelector('select').options).map(o => o.text) : null,
            has_checkbox: !!td.querySelector('input[type=checkbox]'),
            is_readonly: td.classList.contains('htDimmed')
                || td.getAttribute('contenteditable') === 'false',
            is_numeric_aligned: getComputedStyle(td).textAlign === 'right',
            has_link: !!td.querySelector('a'),
            has_badge: !!td.querySelector('[class*=badge], [class*=status], [class*=tag]'),
            classes: Array.from(td.classList),
            background_color: getComputedStyle(td).backgroundColor
        }))
    );

    return {
        framework: 'handsontable',
        headers,
        sample_rows: rows,
        total_rows: container.querySelectorAll('.ht_master tbody tr').length,
        total_cols: headers.length,
        has_frozen_columns: !!container.querySelector('.ht_clone_left'),
        frozen_col_count: container.querySelectorAll('.ht_clone_left thead th').length,
        has_row_headers: !!container.querySelector('.ht_master tbody th'),
        has_column_resize: !!container.querySelector('.manualColumnResizer'),
        has_row_resize: !!container.querySelector('.manualRowResizer'),
        has_merge_cells: !!container.querySelector('[class*=merged]'),
        scroll_height: container.querySelector('.wtHolder')?.scrollHeight || 0,
        visible_height: container.querySelector('.wtHolder')?.clientHeight || 0,
        is_scrollable: (container.querySelector('.wtHolder')?.scrollHeight || 0) >
                      (container.querySelector('.wtHolder')?.clientHeight || 0),
        nested_headers: container.querySelectorAll('.ht_master thead tr').length > 1,
        header_levels: container.querySelectorAll('.ht_master thead tr').length
    };
}"""


class HandsontableExtractor:
    """Extract deep metadata from Handsontable grids via Playwright."""

    async def extract(self, page: Page, grid_selector: str) -> dict | None:
        return await page.evaluate(_EXTRACTION_SCRIPT, grid_selector)

    async def extract_all(self, page: Page) -> list[dict]:
        """Find and extract all Handsontable instances on the page."""
        selectors: list[str] = await page.evaluate("""() =>
            Array.from(document.querySelectorAll('.handsontable'))
                 .map((el, i) => el.id ? '#' + el.id : '.handsontable:nth-of-type(' + (i+1) + ')')
        """)
        results = []
        for sel in selectors:
            data = await self.extract(page, sel)
            if data:
                data["selector"] = sel
                results.append(data)
        return results
