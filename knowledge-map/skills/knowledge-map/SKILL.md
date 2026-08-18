---
name: knowledge-map
description: Use when looking for a value, a decision or a connection in the knowledge documents. Call this before opening a whole file.
---

# Knowledge Map

When you need a value or a decision written in the knowledge documents, **ask here before
you open a file.**

## How to use it

    python "${CLAUDE_PLUGIN_ROOT}/scripts/ask.py" "<question>"
    python "${CLAUDE_PLUGIN_ROOT}/scripts/ask.py" --path "<a>" "<b>"
    python "${CLAUDE_PLUGIN_ROOT}/scripts/ask.py" --explain "<node>"

## Order of work

1. Decide what you are asking about — knowledge we wrote goes here, code goes to the code map.
2. Ask **in the language the knowledge documents are written in**. Another language matches nothing.
3. Ask **narrowly**. Follow the three rules below.
4. The answer carries the statement with its file and line number. That is usually the end of it.
5. Open the lines around it only when you need to confirm. **Do not open the whole file.**
6. If three or more places need looking at, delegate and take only the conclusion.

## Three rules you must follow

- **Ask in the language the knowledge documents are written in.** A question in another
  language matches nothing.
- **The answer budget is 20,000.** Lower it and statements carrying values come back cut.
- **Ask narrowly.** A question after a single value comes back short, far cheaper than
  opening the file. A question that sweeps a whole topic fills the budget with a
  **truncated list**, more expensive than reading one note whole. To sweep a topic, hand it
  to a subagent and take only the conclusion.

## Refreshing

Asking does not refresh anything. Refreshes run at session start, when a delegated task
ends, and before and after compaction. If the map lags, the answer says so.
