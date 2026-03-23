"""Merging outputs from multiple agents into the final spec."""


def merge_spec_sections(*section_dicts: dict) -> dict:
    """Merge multiple partial spec dicts, later dicts take priority on scalar keys."""
    merged: dict = {}
    for d in section_dicts:
        if not isinstance(d, dict):
            continue
        for key, value in d.items():
            if key not in merged:
                merged[key] = value
            elif isinstance(value, list) and isinstance(merged[key], list):
                # Extend lists, deduplicate by identity if possible
                merged[key] = merged[key] + [
                    item for item in value if item not in merged[key]
                ]
            elif isinstance(value, dict) and isinstance(merged[key], dict):
                merged[key] = {**merged[key], **value}
            else:
                # Later value wins for scalars
                merged[key] = value
    return merged


def assign_sequential_ids(spec: dict) -> dict:
    """Assign BTN_NNN, VIEW_NNN, GRID_NNN, INT_NNN IDs to spec items."""
    for i, btn in enumerate(spec.get("buttons", []), 1):
        if not btn.get("btn_index"):
            btn["btn_index"] = f"BTN_{i:03d}"

    for i, view in enumerate(spec.get("views", []), 1):
        if not view.get("view_id"):
            view["view_id"] = f"VIEW_{i:03d}"

    for i, grid in enumerate(spec.get("grids", []), 1):
        if not grid.get("grid_id"):
            grid["grid_id"] = f"GRID_{i:03d}"

    for i, interaction in enumerate(spec.get("state_transitions", []), 1):
        if not interaction.get("transition_id"):
            interaction["transition_id"] = f"INT_{i:03d}"

    return spec
