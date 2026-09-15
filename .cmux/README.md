# cmux knowledge-engineer communication

Task assignment and completion reports for this project use the existing cmux `surface:2` tab, `Confirm knowledge-engineer role | context-graph`, rather than Computer Use or a separate API agent.

```sh
.cmux/knowledge-engineer.sh check
.cmux/knowledge-engineer.sh assign KB-PERF-001 "Validate the Context Pack performance baseline with 50 fixed questions"
.cmux/knowledge-engineer.sh heartbeat KB-PERF-001
.cmux/knowledge-engineer.sh complete KB-PERF-001 complete "Report changed files and verification results"
.cmux/knowledge-engineer.sh recover KB-PERF-001 "Work output has been idle for more than 60 seconds"
```

Rules:

- `check` confirms surface existence, health, and scrollback.
- `assign` sends the work ID and completion-report fields together.
- During active work, send a `heartbeat` every 60 seconds; send `recover` when work stops.
- Completion reports must include `work_id`, `status`, `changed`, `verification`, `unverified`, and `next_action`.
- If the surface disappears, do not create another subagent; re-identify it with `cmux tree --all`.
- Do not mark work complete until re-identification finishes.
