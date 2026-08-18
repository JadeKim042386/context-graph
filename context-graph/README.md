# Knowledge Map

Builds a map by **copying the structure already written in your knowledge documents**
(markdown and HTML). No language model is involved, so hundreds of documents take under
a second, and the same input always gives the same output.

## What you get

- **Value lookup** — the answer carries the statement together with its **file and line number**.
- **Connections** — where separate documents meet.
- **Lineage** — the relations you wrote as `- <word> [[target]]`, used exactly as written.

## First run

1. You answer where the knowledge documents live.
2. It asks whether to install the two tools it uses (`graphify`, `obsidian-second-brain`).
   Decline and the map still builds.
3. It builds the map and shows a **score**. A low score comes with what is wrong.
4. You pick the compaction threshold.

## How to ask

    python "${CLAUDE_PLUGIN_ROOT}/scripts/ask.py" "<question>"
    python "${CLAUDE_PLUGIN_ROOT}/scripts/ask.py" --path "<a>" "<b>"
    python "${CLAUDE_PLUGIN_ROOT}/scripts/ask.py" --explain "<node>"

## When it refreshes

Only at four points: session start, when a delegated task ends, right before compaction,
and right after it. Asking does not refresh anything. If the map lags the documents, the
answer says so.

## Limits

- **Ask in the language the knowledge documents are written in.** A question in another
  language matches nothing.
- **The answer budget is 20,000.** Lower it and statements carrying values come back cut.
- **Ask narrowly.** A question after a single value ("tray piece length median") comes back
  in a few hundred characters, far cheaper than opening the file. A question that sweeps a
  whole topic ("clustering objective function overall") fills the budget with a **truncated
  list**, more expensive than reading one note whole. To sweep a topic, hand it to a
  subagent and take only the conclusion.
- Past 800 documents a query takes more than 5 seconds. At that point consider splitting the
  map into branches.
