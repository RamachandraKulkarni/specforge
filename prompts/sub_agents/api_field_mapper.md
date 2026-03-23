Match these API fields to column headers.

API FIELDS (from response object):
{{api_fields}}

COLUMN HEADERS:
{{column_headers}}

SAMPLE API VALUES: {{api_sample_values}}
SAMPLE CELL VALUES: {{cell_sample_values}}

Respond with a JSON array:
[{"header": "exact header text", "api_field": "matched field or null", "confidence": 0.0-1.0, "match_type": "exact | case_normalized | abbreviation | semantic | value_match | none", "evidence": "brief reason"}]
