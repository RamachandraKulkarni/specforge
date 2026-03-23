"""Schema validation (jsonschema) for the final spec output."""

import jsonschema

from specforge.assembler.spec_template import SPEC_JSONSCHEMA


class SpecValidator:
    """Validate the generated spec against the canonical JSON schema."""

    def validate(self, spec: dict) -> dict:
        errors = []
        warnings = []

        # JSON schema validation
        try:
            jsonschema.validate(instance=spec, schema=SPEC_JSONSCHEMA)
        except jsonschema.ValidationError as e:
            errors.append({"type": "schema_error", "message": e.message, "path": list(e.path)})
        except jsonschema.SchemaError as e:
            errors.append({"type": "schema_definition_error", "message": str(e)})

        # Internal consistency checks
        btn_ids = {b.get("btn_index") for b in spec.get("buttons", [])}
        grid_ids = {g.get("grid_id") for g in spec.get("grids", [])}
        view_ids = {v.get("view_id") for v in spec.get("views", [])}

        # Check cross-references
        for ref in spec.get("cross_references", []):
            if ref.get("btn_index") and ref["btn_index"] not in btn_ids:
                errors.append({"type": "dangling_reference", "field": "btn_index", "value": ref["btn_index"]})
            if ref.get("grid_id") and ref["grid_id"] not in grid_ids:
                errors.append({"type": "dangling_reference", "field": "grid_id", "value": ref["grid_id"]})

        # Warn on empty sections
        for section in ("buttons", "grids", "navigation"):
            if not spec.get(section):
                warnings.append({"type": "empty_section", "section": section})

        return {"errors": errors, "warnings": warnings, "valid": len(errors) == 0}
