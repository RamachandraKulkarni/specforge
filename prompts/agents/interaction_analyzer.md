Analyze these {{batch_size}} interactions from screen {{screen_id}} ({{view_flow_type}}).

PAGE: {{page_url}}
SCREEN PURPOSE: {{screen_purpose}}

{{interactions}}

Respond:
{"screen_id": "{{screen_id}}", "interactions": [{"interaction_id": "INT_NNN", "trigger_element_id": "string", "trigger_label": "string", "interaction_type": "button_click | tab_switch | filter_apply | form_submit | context_menu_select | row_select | column_sort | column_filter | drag_drop", "click_action": {"type": "api_call | api_call_then_refresh | navigation | modal_open | modal_close | tab_switch | filter_update | grid_refresh | toggle_visibility | form_submit | download | composite", "steps": [{"step": int, "action": "api_call | refresh_grid | navigate | open_modal | close_modal | update_ui | show_toast | download_file | enable_element | disable_element | show_element | hide_element | update_text | clear_selection", "detail": {"method": "GET | POST | PUT | DELETE", "endpoint": "API URL", "payload_source": "selected_rows | form_fields | current_filters | none", "payload_fields": [], "target_grid": "grid_ref", "target_url": "URL", "modal_id": "string", "element_selector": "CSS", "change_type": "disabled | enabled | hidden | visible | text_update", "new_value": "string"}}]}, "preconditions": [{"type": "row_selected | form_valid | field_not_empty | status_equals | none", "detail": "string"}], "state_transition": {"from_state": "descriptive_name", "to_state": "descriptive_name", "reversible": bool, "reverse_trigger": "element_id or null"}, "error_handling": {"type": "toast_notification | inline_error | modal_error | none", "position": "top_right | bottom_center | inline | modal", "auto_dismiss": bool}, "confidence": 0.0-1.0}]}
