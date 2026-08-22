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
    python "${CLAUDE_PLUGIN_ROOT}/scripts/ask.py" --chain "<decision>"
    python "${CLAUDE_PLUGIN_ROOT}/scripts/ask.py" --conflicts
    python "${CLAUDE_PLUGIN_ROOT}/scripts/ask.py" --settle "1:2 2:3"

## Decision causality

Write the cause in the later decision document as a relation line:

    - caused_by [[ADR 0071]]

`--chain` then shows what a decision came from and what it led to, three steps out, with the
file and line for each. It stops on a cycle, so a miswritten pair cannot loop it. Relations
already in use between decisions (`supersedes`, `corrects`, `refines`, `follows`, `continues`,
`extends`) are listed apart as nearby decisions - they are not treated as cause. Nothing is
inferred from prose: the map copies what a person wrote.

## Values two documents state differently

Every refresh writes a sidecar beside the map (`<map>.conflicts.txt`) naming values that two
documents state differently. It is never mixed into an answer - a rule-based check misfires,
and a warning that is sometimes wrong drags down the trust in every answer beside it.

`--conflicts` lists them ten at a time with the file and line for each value. `--settle
"1:2 2:3"` reads `conflict number : choice` and does one of three things: keep the value you
picked and fix the document that has the other, mark the pair "not a conflict", or leave it.
Add `--dry-run` to see what would change without touching a file.

Fixing edits the document, not the map: the map is rebuilt from documents, so a map-only fix
would leave the two disagreeing forever. Every edit is appended to `<map>.resolutions.log`
with the file, line, old value and new value, and a document that changed since the map was
built is skipped rather than overwritten. A "not a conflict" mark is stored with the set of
values it had at the time, so it releases itself as soon as any of them changes.

Add `watched_names` to the config to have specific value names read first:

    "watched_names": ["bend radius", "tray width", "tier gap"]

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
