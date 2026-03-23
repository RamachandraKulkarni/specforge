Analyze this data grid and produce column specifications.

CONTEXT: Screen {{screen_id}} | {{view_flow_type}} | {{iso}} {{module}}
GRID FRAMEWORK: {{grid_framework}}

DOM-EXTRACTED COLUMNS:
{{column_dom_metadata}}

SAMPLE DATA (first {{sample_row_count}} rows):
{{sample_cell_data}}

API RESPONSE MAPPING:
Endpoint: {{api_endpoint}} ({{api_method}})
Response fields: {{api_response_fields}}

GRID PROPERTIES:
- Frozen columns: {{has_frozen_columns}} (count: {{frozen_col_count}})
- Row headers: {{has_row_headers}}
- Column resize: {{has_column_resize}}
- Nested headers: {{nested_headers}} ({{header_levels}} levels)
- Total rows: {{total_rows}} | Total cols: {{total_columns}}
- Scrollable: {{is_scrollable}}

{{chunk_note}}

Respond:
{"table_id": "{{table_id}}", "grid_ref": "descriptive_snake_case", "data_source": {"endpoint": "string", "method": "GET|POST", "response_root": "dot.notation.path", "total_count_field": "dot.notation or null"}, "columns": [{"col_key": "UPPER_SNAKE_CASE", "header_label": "exact header text", "data_type": "string | numeric | integer | decimal | currency | percentage | date | datetime | boolean | enum | id | computed", "format": "alphanumeric_id | currency_2dp | percentage_1dp | date_mmddyyyy | datetime_iso | boolean_yesno | enum_status | text_freeform | numeric_integer | numeric_mw | numeric_price | null", "editable": bool, "sortable": bool, "sort_default": "ascending | descending | none", "filterable": bool, "filter_type": "text_contains | text_exact | numeric_range | date_range | enum_dropdown | boolean_toggle | none", "width_px": int, "min_width_px": int, "resizable": bool, "frozen": bool, "hidden_by_default": bool, "validation": {"type": "range | regex | enum | length | required | null", "min": "if range", "max": "if range", "options": ["if enum"], "required": bool}, "source_api_field": "exact API field name", "renderer": "text | numeric | date | checkbox | dropdown | status_badge | link | html | custom", "editor": "text | numeric | date_picker | dropdown | checkbox | autocomplete | null", "conditional_formatting": [{"condition": "description", "style": "description"}], "confidence": 0.0-1.0}], "row_expansion": {"enabled": bool, "trigger": "click_row | expand_icon | double_click", "content_type": "detail_panel | sub_grid | form | none"}, "context_menu": [{"label": "string", "action": "clipboard_copy | open_modal | navigate | api_call", "requires_selection": bool}], "selection_mode": "single_row | multi_row | single_cell | cell_range | none", "pagination": {"type": "client_side | server_side | virtual_scroll | none", "page_size": int}, "summary_row": {"enabled": bool, "position": "top | bottom", "aggregations": []}}
