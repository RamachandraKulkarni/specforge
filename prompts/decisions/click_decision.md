Should I click this element? I'm building a UI spec for {{iso}} {{module}}.

ELEMENT:
- Tag: {{tag}}
- Text: "{{text}}"
- Aria-label: "{{aria_label}}"
- Classes: {{classes}}
- Href: {{href}}
- Type: {{input_type}}
- Position: {{position}} on page
- Parent context: {{parent_context}}

CURRENT SCREEN: {{screen_url}}
SCREENS ALREADY VISITED: {{visited_count}}
EXPLORATION DEPTH: {{current_depth}} of max {{max_depth}}

SKIP PATTERNS (do NOT click):
- Logout, sign out, session management
- Help, documentation, external links
- Language/locale switchers
- Notification bells, user profile menus
- Elements that navigate to other ISO modules
- Print-only buttons (unless revealing print layout structure)
- Social sharing buttons

HIGH PRIORITY (DO click):
- Buttons labeled: Submit, Create, Add, Edit, Delete, Approve, Reject, Import, Export, Save, Run, Execute, Calculate, Refresh
- Tab controls that reveal different views
- Filter/search controls on grids
- Navigation tabs within the module
- Expand/collapse controls on grids
- Context menu triggers (right-click areas)

Respond:
{"action": "click | skip | defer", "priority": 1-10, "reason": "brief rationale", "expected_result": "navigation | modal | content_change | grid_refresh | download | filter_update | tab_switch | unknown", "defer_until": "row_selected | specific_state | null"}
