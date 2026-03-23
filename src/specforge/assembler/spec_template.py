"""JSON spec schema template — the canonical output shape."""

import datetime


def empty_spec(iso: str, module: str) -> dict:
    """Return a blank spec skeleton matching the SpecForge v2 schema."""
    return {
        "iso": iso,
        "module": module,
        "version": "1.0.0",
        "generated_at": datetime.datetime.now().isoformat(),
        "generator": "specforge/2.0.0",
        "statistics": {
            "total_screens": 0,
            "total_buttons": 0,
            "total_grids": 0,
            "total_api_endpoints": 0,
            "generation_cost_usd": 0.0,
        },
        "navigation": {
            "entry_point": "",
            "primary_tabs": [],
            "tab_to_view_mapping": {},
        },
        "buttons": [],
        "views": [],
        "grids": [],
        "api_endpoints": [],
        "cross_references": [],
        "state_transitions": [],
        "visibility_rules": [],
        "validation_gaps": [],
    }


SPEC_JSONSCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["iso", "module", "version", "navigation", "buttons", "grids"],
    "properties": {
        "iso": {"type": "string"},
        "module": {"type": "string"},
        "version": {"type": "string"},
        "generated_at": {"type": "string"},
        "generator": {"type": "string"},
        "statistics": {
            "type": "object",
            "properties": {
                "total_screens": {"type": "integer"},
                "total_buttons": {"type": "integer"},
                "total_grids": {"type": "integer"},
                "total_api_endpoints": {"type": "integer"},
                "generation_cost_usd": {"type": "number"},
            },
        },
        "navigation": {
            "type": "object",
            "required": ["entry_point"],
            "properties": {
                "entry_point": {"type": "string"},
                "primary_tabs": {"type": "array"},
                "tab_to_view_mapping": {"type": "object"},
            },
        },
        "buttons": {"type": "array"},
        "views": {"type": "array"},
        "grids": {"type": "array"},
        "api_endpoints": {"type": "array"},
        "cross_references": {"type": "array"},
        "state_transitions": {"type": "array"},
        "visibility_rules": {"type": "array"},
        "validation_gaps": {"type": "array"},
    },
}
