---
name: context-graph
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
2. Ask **in the language the document you want is written in**. A question in another language
   reaches only the notes written in that language, and mostly returns near-misses.
3. Ask **narrowly**. Follow the three rules below.
4. The answer carries the statement with its file and line number. That is usually the end of it.
5. Open the lines around it only when you need to confirm. **Do not open the whole file.**
6. If three or more places need looking at, delegate and take only the conclusion.

## Three rules you must follow

- **Ask in the language the document you want is written in.** Matching is on the words as
  they are written, so a question in another language reaches only the notes in that
  language. It is not silent about it - it returns whatever it can find, and most of that is
  a near-miss. If a value is written in an English note, ask for it in English.
- **The answer is capped in characters** (`answer_budget`, 8,000 by default). Statements are
  dropped whole from the back, never cut in the middle, and the count of what was dropped is
  printed at the end. **A dropped count means you asked too broadly** - it does not mean the
  documents hold nothing more.
- **Ask narrowly.** A question after a single value comes back short and costs less than
  opening the file. A question that sweeps a whole topic fills the cap and reports what it
  had to leave out, which tells you less than reading one note whole. To sweep a topic, hand
  it to a subagent and take only the conclusion.

## Refreshing

Asking does not refresh anything. Refreshes run at session start, when a delegated task ends,
and after compaction. If the map lags the documents, the answer says so and names what changed.
