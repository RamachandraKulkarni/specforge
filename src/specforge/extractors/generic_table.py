"""Fallback HTML table extraction for DataTables and generic <table> elements."""

from playwright.async_api import Page

_GENERIC_SCRIPT = """(selector) => {
    const table = document.querySelector(selector);
    if (!table) return null;

    const isDataTables = table.classList.contains('dataTable') || !!table.closest('.dataTables_wrapper');

    const headers = Array.from(table.querySelectorAll('thead th, thead td')).map((th, i) => ({
        index: i,
        text: th.innerText.trim(),
        sortable: th.classList.contains('sorting') || th.classList.contains('sorting_asc') || th.classList.contains('sorting_desc'),
        sort_direction: th.classList.contains('sorting_asc') ? 'asc'
            : th.classList.contains('sorting_desc') ? 'desc' : null,
        colspan: th.colSpan || 1,
        classes: Array.from(th.classList)
    }));

    const rows = Array.from(table.querySelectorAll('tbody tr')).slice(0, 5).map((tr, ri) =>
        Array.from(tr.querySelectorAll('td, th')).map((td, ci) => ({
            row: ri,
            col: ci,
            value: td.innerText.trim().substring(0, 200),
            has_input: !!td.querySelector('input'),
            has_link: !!td.querySelector('a'),
            has_button: !!td.querySelector('button'),
            classes: Array.from(td.classList)
        }))
    );

    const wrapper = table.closest('.dataTables_wrapper');
    const paginationInfo = wrapper
        ? wrapper.querySelector('.dataTables_info')?.innerText?.trim() || null
        : null;

    return {
        framework: isDataTables ? 'datatables' : 'generic',
        headers,
        sample_rows: rows,
        total_rows: table.querySelectorAll('tbody tr').length,
        total_cols: headers.length,
        has_pagination: isDataTables && !!wrapper?.querySelector('.dataTables_paginate'),
        has_search: isDataTables && !!wrapper?.querySelector('.dataTables_filter'),
        has_length_control: isDataTables && !!wrapper?.querySelector('.dataTables_length'),
        pagination_info: paginationInfo
    };
}"""


class GenericTableExtractor:
    """Extract metadata from generic HTML tables and DataTables instances."""

    async def extract(self, page: Page, selector: str) -> dict | None:
        return await page.evaluate(_GENERIC_SCRIPT, selector)

    async def extract_all(self, page: Page) -> list[dict]:
        selectors: list[str] = await page.evaluate("""() =>
            Array.from(document.querySelectorAll('table'))
                 .map((el, i) => el.id ? '#' + el.id : 'table:nth-of-type(' + (i+1) + ')')
        """)
        results = []
        for sel in selectors:
            data = await self.extract(page, sel)
            if data:
                data["selector"] = sel
                results.append(data)
        return results
