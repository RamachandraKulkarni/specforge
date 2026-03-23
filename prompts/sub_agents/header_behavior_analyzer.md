Analyze these column headers from a {{grid_framework}} grid.

COLUMNS WITH DOM METADATA:
{{columns_with_dom}}

OBSERVED SORT INDICATORS: {{sort_indicators}}
OBSERVED FILTER ELEMENTS: {{filter_elements}}

Respond:
{"columns": [{"col_key": "string", "sort_behavior": {"enabled": bool, "direction": "asc | desc | bidirectional | none", "is_default_sort": bool}, "filter_behavior": {"enabled": bool, "type": "text_contains | text_exact | numeric_range | date_range | enum_dropdown | boolean_toggle | custom | none", "options": ["if enum"]}, "header_interaction": {"click_sorts": bool, "has_dropdown": bool, "has_resize_handle": bool, "is_draggable": bool}}]}
