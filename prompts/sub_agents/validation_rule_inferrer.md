Infer validation rules for these columns.
COLUMN SPECS (from main analysis): {{column_specs}}
SAMPLE VALUES (5 rows): {{sample_values}}
EDITOR TYPES DETECTED: {{editor_types}}

Respond:
{"validations": [{"col_key": "string", "required": bool, "validation_type": "range | regex | enum | length | custom | none", "constraints": {"min": "if range", "max": "if range", "pattern": "if regex", "min_length": "if length", "max_length": "if length", "allowed_values": ["if enum"]}, "error_message_pattern": "observed or inferred", "confidence": 0.0-1.0}]}
