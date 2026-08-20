<div align="center">

# Context Graph

### Ask your notes a question. Get the sentence back, with the file and line it sits on.

**A Claude Code plugin · Copies the structure you already wrote · No language model · 100% local**

[![Tests](https://img.shields.io/badge/tests-57%20passing-brightgreen.svg)](#tests)
[![No LLM](https://img.shields.io/badge/build-no%20LLM%20calls-brightgreen.svg)](#why-it-copies-instead-of-inferring)
[![Deterministic](https://img.shields.io/badge/output-byte--identical-brightgreen.svg)](#same-input-same-output)
[![Python](https://img.shields.io/badge/python-3.9%2B%20stdlib%20only-blue.svg)](#requirements)

[![Windows](https://img.shields.io/badge/Windows-supported-blue.svg)](#requirements)
[![macOS](https://img.shields.io/badge/macOS-supported-blue.svg)](#requirements)
[![Linux](https://img.shields.io/badge/Linux-supported-blue.svg)](#requirements)

**182 documents · 8,524 nodes · rebuilt in 0.11 s**

</div>

---

<div align="center">
<img alt="A Claude Code session on the left and the map on the right: you ask in your own words, the skill runs the lookup, the statement that matches lights up together with the nodes around it, a path walks the supersedes chain between decisions, and at compaction the session is written back into the notes and the map is rebuilt" src="assets/demo.gif" width="900">
</div>

**What it is** — your notes already say what links to what. This copies that structure into one
map, then answers a question with **the statement itself, its file and its line number**, instead
of making you open the file. Nothing is guessed: a statement in the map is the statement in the
document, word for word. Building 182 documents takes about a tenth of a second and calls no model.

The animation above is the whole loop, from the side you use and the side you do not see. You ask
Claude Code in your own words; the skill turns that into a lookup on the map (the `ask.py` line);
the statement that matches lights up **together with the nodes around it**, which is what comes
back with the answer; a second question walks the relation words themselves; and when the
conversation is compacted the session is written back into your notes and the map is rebuilt, so
the next question already finds it. Every statement in your notes is a node, and every
`- supersedes [[...]]` you wrote is an edge.

| Ask this | Get this |
|---|---|
| `ask.py "<question>"` | the statements that match, each with its file and line |
| `ask.py --path "<a>" "<b>"` | the chain of relations linking two decisions |
| `ask.py --explain "<node>"` | one node and its neighbours |

---

## Contents

- [The problem](#the-problem)
- [Install](#install)
- [Point it at your notes](#point-it-at-your-notes)
- [Why it copies instead of inferring](#why-it-copies-instead-of-inferring)
- [How it works](#how-it-works)
- [Command reference](#command-reference)
- [When it refreshes](#when-it-refreshes)
- [Quality check](#quality-check)
- [Limits](#limits)
- [Requirements](#requirements)
- [Tests](#tests)
- [Troubleshooting](#troubleshooting)

---

## The problem

Once knowledge documents pile up, **a single check means reading a whole file** — and every
one of those reads lands in the model's context before it can answer anything.

Counted on the set of documents this was built against: catching up on one thread of work means
reading **289,000 characters**; finding the right document means reading a **49,000 character**
index; and the **1,746 links** already written between documents can only be followed by opening
the file at the other end.

The information was already written down. What cost anything was getting back to it.

```
$ python ask.py "tray piece length median"

NODE Piece size: longest edge min 0.05 m, **median 1.19 m**, max 99.44 m.
     [src=knowledge\facts\WHRP Plant - Model Contents and Structure Regions - Facts.md loc=192]
NODE Tray pieces attached to no structure rise from 1,033 (18.2%) to 1,141 (25.8%) - the
     structure areas now cover less of the routing.
     [src=knowledge\decisions\ADR 0086 APOC Drops 20 Structure Areas and Their Trays.md loc=33]
...
[also touched: cable_project Handoff, index, WHRP Plant - Model Contents and Structure
 Regions - Facts, Browser 3D Viewers - Facts and 10 more]
```

The statement that matched comes first, the statements around it follow, and the documents they
sit in are named once at the end. Long answers keep going in the same shape; the middle of this
one is cut here to keep the example short.

**You get the statement itself, plus the file and line number it sits on.** That is usually
the end of it; you open the surrounding lines only when you need to confirm. Reading drops
from tens of thousands of characters to a few hundred.

---

## Install

Two commands in Claude Code, then a restart.

### 1. Add the marketplace

```
/plugin marketplace add JadeKim042386/context-graph
```

Nothing to clone — Claude Code fetches it for you.

### 2. Install the plugin

```
/plugin install context-graph
```

This brings the skill and the refresh hooks with it.

### 3. Restart Claude Code

The hooks and the skill only attach on start.

### 4. Check that it took

```
/plugin
```

Seeing `context-graph` in the list is enough.

### Installing from a local clone instead

Use this when you want to change the code and see it immediately.

```bash
git clone https://github.com/JadeKim042386/context-graph.git
```

```
/plugin marketplace add <clone-path>
/plugin install context-graph
```

A marketplace added from a directory reads the files as they are on disk, so an edit shows up
on the next restart without any publishing step.

### Updating

```
/plugin marketplace update context-graph
```

### Uninstall

```
/plugin uninstall context-graph
/plugin marketplace remove context-graph
```

The map file and the config live **outside** the knowledge documents, so removing the plugin
does not change a single character of them.

---

## Point it at your notes

No path is baked into the code, so the one thing you have to do is say where your documents are.
Write `~/.claude/context-graph/config.json` (or point the `KNOWLEDGE_MAP_CONFIG` environment
variable at a file of your own):

```json
{
  "source_dirs": ["C:/notes", "C:/another/folder"],
  "map_path": "C:/notes-map/graph.json",
  "answer_budget": 20000
}
```

- **`source_dirs`** — one or more folders holding your `.md`, `.markdown`, `.html` or `.htm`
  documents. They are only ever read
- **`map_path`** — where the map goes. Keep it **outside** those folders, or the map is picked
  up as a document on the next build. The query tool needs the `.json` suffix
- **`answer_budget`** — how large an answer may grow before it is cut. Lower it and long
  statements lose the tail, which is usually where the figure is

Then build it once:

```bash
python build_map.py
```

```
nodes 8524 · links 9749 · located 99.8% · relations 28 kinds · components 3 · samples 5/5 verbatim · 0.11s
```

**That line is where you find out whether it is any use on your set of documents** — what it
means is under [Quality check](#quality-check). If the folder is missing or holds no documents, the
build says so instead of quietly producing an empty map.

### The two tools it leans on

| | Without it |
|---|---|
| [graphify](https://github.com/safishamsi/graphify) — runs the queries | building and scoring still work; asking does not |
| [obsidian-second-brain](https://github.com/eugeniughelbur/obsidian-second-brain) — writes a session into your notes | everything works except the write-back at compaction |

Neither is installed for you.

---

## Why it copies instead of inferring

The relations between documents are **already written down**, by hand, by the person who wrote
the notes.

```markdown
## Decision
- Split the rack along its length by equipment connection density alone: 8 or more endpoints in a 5 m window.

## Relations
- supersedes [[earlier decision]]
- relates_to [[related fact]]
```

Asking a model to infer that relation would be paying to guess at something already stated.
Copying it across instead is what makes the map

- **fast** — 0.11 s for 182 documents
- **free** — zero model calls
- **not wrong** — a statement in the map is the statement in the document, verbatim
- **repeatable** — build twice, get byte-identical output

### Same input, same output

Every file walk and every set iteration is sorted and pinned. A test builds the map twice and
compares it byte for byte. That test has to pass before any of the others mean anything —
**if the output changes every run, no fix can be shown to have improved anything.**

---

## How it works

<img alt="Statements and the relations you wrote are copied into one map that answers with a value, a connection or a lineage" src="assets/structure.png" width="880">

### What becomes a node

| Node | What it is | Location |
|---|---|---|
| Document | one file | file + line 1 |
| Heading | any of `#` to `######` (`h1`-`h3` in HTML), including the body under it | file + line |
| **Statement** | one paragraph or list item under a heading | file + line |
| Name-only node | a target that is pointed at but exists in no document | none |

**The values live in the statement nodes.** Which is why statement labels are never cut — cut
at 400 characters and the figures at the end disappear from the answers.

### What becomes a link

```
- <word> [[target]]   ->  that word is the relation name (supersedes, follows, corrects ...)
- 대체함 [[target]]     ->  a Korean relation word, stored under its English name (supersedes)
   [[target]]          ->  a mention
```

**A relation word may be written in any script.** Korean notes keep their lineage instead of
losing it to an unnamed mention. The common Korean words are mapped onto the English names the
rest of the map uses — `대체함`/`대체` to `supersedes`, `관련`/`참고` to `relates_to`, `후속` to
`follows`, `정정` to `corrects`, `포함` to `part_of`, and a few more — so a path can run through
documents written in both languages. This is a fixed table in the source, not a translation
service: **no model is called**, and a word outside the table is kept exactly as it was written.
The word still has to be the only thing between the bullet and the link — `- this decision
supersedes [[X]]` is a mention, not a relation.

**It reads the shape of the line, not the name of the section.** So it works on documents with
no `## Relations` section. When a name does not match, it retries with punctuation swapped
(`/`, `:` vs `-`); if there is still no match, it creates a name-only node and links to that.

### HTML follows the same rules

Title becomes the document name, `h1`-`h3` become headings, `p` and `li` become statements,
`a href` becomes a link, tables go one row at a time. **Images, styling and scripts are dropped,
but text inside SVG is kept** — the point a diagram makes usually lives in that text.

### From a question to an answer

<img alt="A question goes to the map, the answer carries the statement and its file and line, and the map is rebuilt at four points" src="assets/flow.png" width="880">

---

## Command reference

### `ask.py "<question>"`

Finds the statements that match the question and returns **the statement itself with its file
and line number**.

```bash
python ask.py "chunk boundary equipment endpoint density"
```

### `ask.py --path "<a>" "<b>"`

Shows the shortest chain linking two nodes. Use it to **follow the lineage of a decision**.

```
$ python ask.py --path "ADR 0024 endpoint_dist Global Normalization Replaces Per-Chunk Min-Max"                 "ADR 0023 GNN Coordinates from Excel mm + Per-Chunk MinMax Normalization"

Shortest path (1 hops):
  ADR 0024 endpoint_dist Global Normalization Replaces Per-Chunk Min-Max
  --supersedes_partially--> ADR 0023 GNN Coordinates from Excel mm + Per-Chunk MinMax Normalization
```

Names have to be given in full, and the chain is labelled with the relation words as they were
written. Where a decision both names an earlier one in prose and lists it under `## Relations`,
the named relation is the one that shows — the bare mention is dropped so it cannot hide the
lineage.

### `ask.py --explain "<node>"`

Shows one node and its neighbours. Use it the first time you meet an unfamiliar term.

### `build_map.py`

Rebuilds the map. This is what the refresh hooks call.

```bash
python build_map.py                    # scans the folders named in the config
python build_map.py --source <path> --out <map-file>
python build_map.py --quiet            # no score printed
```

---

## When it refreshes

**Asking does not refresh anything.** It runs at four points only.

| When | What |
|---|---|
| A session starts or resumes | rebuild the map |
| **A delegated task (subagent) ends** | rebuild the map |
| Right before the conversation is compacted | ask for the session to be written into the knowledge documents |
| Right after the conversation is compacted | rebuild the map |

**Why compaction is two points** — the first hook prints the reminder that the session should be
written into your notes, which the document tool then does; the second rebuilds the map so what
was just written is on it. At the exact spot where context is squeezed out, the knowledge moves
onto the map instead of being lost with the conversation.

### It rebuilds everything

It does not pick out only the changed files. At this size there is nothing left to win — a few
hundred documents rebuild in a tenth of a second — and a change-picking mechanism has to remember
"what changed", which is a second thing that can drift and leave **stale content alive**.

Before a question it checks whether any document is newer than the map, which costs a couple of
milliseconds over a few hundred files, and it only **tells you**.

```
[The map is behind 1 document(s) — WHRP Plant... It is refreshed at the next compaction]
```

It never quietly serves a stale answer.

---

## Quality check

**A map can build cleanly and still be half useless.** So every build scores itself on five
things.

| Measured | What a low value means |
|---|---|
| Share of nodes with a location | value lookup does not work |
| Share of nodes that are a whole file | the map is just a list of documents |
| Number of relation kinds | there is no lineage |
| Components and isolated nodes | path finding fails |
| **Sampled value lookup** | the four above can look fine and it still finds nothing |

**The sampled lookup runs on every build**, and its result is the `samples 5/5 verbatim` part of
the score line. It picks statements carrying numbers in a fixed way, opens the file and line each
one points at, and **checks the statement is still there on that line, word for word**. A sample
that no longer matches is named on the spot.

A low score comes with the cause.

```
located 12% — many documents carry headings only, with no body text under them
few relation kinds — the `- <word> [[target]]` shape is almost absent
```

**A low score does not block anything.** You get to use it knowing what does not work.

### An empty map says why

A map that comes out with nothing in it names the cause, at every refresh point, whether or not
the score is being printed.

```
[the document folder in the config is not there - C:\notes\vualt]
[no .md, .markdown, .html or .htm documents under C:\notes]
```

**A mistyped path and an empty folder used to look identical** — both ended at `nodes 0`. Now the
first line appears when the folder named in the config is not on disk, and the second when the
folder is there but holds no documents.

---

## Limits

Three of them, stated plainly. The last two are measured.

### 1. Ask in the language the knowledge documents are written in

The map does not recognise the same meaning in different words. Ask in Korean about English
documents and **nothing matches at all.** Whatever language you ask in, match **the documents**.

Relation words are the one exception: `- 대체함 [[X]]` and `- supersedes [[X]]` end up as the
same relation, so lineage still runs across a set of documents written in both languages.

### 2. Ask narrowly

| Question | Answer | Compared to |
|---|---|---|
| `tray piece length median` | statement + line number, a few hundred characters | **far cheaper** than opening the file |
| `correlation clustering local search move objective` | a truncated list filling the budget, 20k tokens | **more expensive** than reading one note |

To sweep a whole topic, hand it to a subagent and take **the conclusion only**. If an answer is
truncated, it says so on the spot.

### 3. Queries slow down as the map grows

Two sizes were measured, one ten times the other.

| | 248 documents | 2,480 documents |
|---|---|---|
| Rebuild | 0.24 s | 2.13 s |
| **Query** | 1.80 s | **15.46 s** |

**The query is what gives way first, not the refresh.** A rebuild ten times the size is still
about two seconds; a question at that size takes a quarter of a minute, which is longer than
opening the file would have taken. Between those two points a question stops feeling instant
somewhere in the high hundreds of documents. Past that the map has to be split, with the
question sent only to the branch it belongs to — which this does not do for you.

---

## Requirements

| | |
|---|---|
| Python | 3.9 or newer. **Standard library only** — nothing to pip install for the plugin itself |
| OS | Windows · macOS · Linux |
| Queries | [graphify](https://github.com/safishamsi/graphify), a local CLI. See [the two tools it leans on](#the-two-tools-it-leans-on) |

Nothing in the build or the query reaches the network.

---

## Tests

```bash
python -m pytest context-graph/tests -v
```

**All 57 pass.** Three of them matter most.

- **Same input, same output** — build twice, compare byte for byte
- **Sampled value lookup** — compare a statement in the map against that line in the source file
- **Odd documents** — cases met in real use, kept as test material: a date read as a relation
  name, an empty file, and prose continuing after the relations section, which used to drop
  every statement below it

---

## Troubleshooting

### Text comes out garbled, or `UnicodeEncodeError`

The default console encoding on a Korean Windows box cannot write characters such as an em
dash. The scripts pin their output to UTF-8 at startup, so this usually does not happen. If it
still does:

```bash
PYTHONIOENCODING=utf-8 python ask.py "<question>"
```

### The question returns nothing

Check that you **asked in the language of the documents**. English documents need an English
question.

### The answer comes back truncated

The question was too broad. Narrow the words, or hand the topic to a subagent.

### The map answers with stale content

Refreshes run only at session start, when a delegated task ends, and before and after
compaction, and the answer tells you when the map is behind. To bring it up to date right now:

```bash
python build_map.py
```

### The score comes out low

The map does not fit that set of documents well. Read the hints that come with the score —
usually the body under the headings is empty, or there are no `- <word> [[target]]` relations.

---

## License

MIT
