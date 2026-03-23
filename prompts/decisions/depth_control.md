Should I continue exploring from this point?

EXPLORATION STATE:
- Current depth: {{current_depth}} / max {{max_depth}}
- Total screens discovered: {{total_screens}}
- Screens fully analyzed: {{analyzed_screens}}
- New unique tables found in last 5 screens: {{recent_new_tables}}
- New unique buttons found in last 5 screens: {{recent_new_buttons}}
- New unique API endpoints in last 5 screens: {{recent_new_endpoints}}
- API cost so far: ${{cost_so_far}} / max ${{max_cost}}
- Time elapsed: {{time_elapsed}} min
- Exploration queue remaining: {{queue_size}} elements

DIMINISHING RETURNS SIGNAL: If last 5 screens yielded <2 new tables and <3 new buttons, consider wrapping up this branch.

Respond:
{"action": "go_deeper | go_wider | skip_branch | wrap_up", "reason": "brief", "recommended_next": "specific suggestion if go_wider"}
