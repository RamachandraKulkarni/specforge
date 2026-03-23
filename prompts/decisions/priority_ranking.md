Rank these {{element_count}} elements from screen "{{screen_title}}" ({{screen_url}}).
I'm building a spec for {{iso}} {{module}}.

ELEMENTS:
{{elements_json}}

CONTEXT:
- Screen classified as: {{view_flow_type}}
- Tables on screen: {{table_count}}
- Already explored from this screen: {{already_explored}}
- Total budget remaining: {{budget_remaining}} elements

RANKING CRITERIA (most to least important):
1. MANAGEMENT actions (Submit, Create, Approve) → 9-10
2. Tab/navigation controls revealing new views → 8-9
3. Data manipulation (Edit, Delete, Import, Export) → 7-8
4. Filter/sort controls on data grids → 6-7
5. VIEW-only buttons (reports, summaries) → 5-6
6. SETTINGS/configuration → 4-5
7. MISC/utility → 2-3
8. Already explored or likely duplicates → 1

Respond:
{"rankings": [{"element_id": "...", "priority": 1-10, "reason": "brief"}]}
