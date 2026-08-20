"""Builds the readme's hero animation: the terminal on the left, the map on the right.

The point of the animation is to show what happens *inside* when you ask: the documents
become a map, the question lights up the statement that matches together with the nodes
around it, a path walks the relations someone wrote by hand, and the map is rebuilt when
the session is written back into the notes.

Every frame is one HTML page rendered by headless Chrome; the frames are stitched into a
GIF with per-frame durations, so typing runs fast and the answers stay up long enough to
read. The terminal transcript is copied from a real run against the sample documents in
scratchpad/demo.
"""
import html
import os
import subprocess
import sys

from PIL import Image

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
FRAME_DIR = os.path.join(OUTPUT_DIR, "frames")
WIDTH, HEIGHT = 1060, 470

# ---------------------------------------------------------------- the map on the right

# Statement nodes carry a value; document nodes are the files they sit in.
GRAPH_NODES = {
    "fact_doc":   {"x": 132, "y": 150, "kind": "document", "label": "Fleet Facts"},
    "swap":       {"x": 60,  "y": 74,  "kind": "statement", "label": "18%"},
    "charge":     {"x": 205, "y": 66,  "kind": "statement", "label": "42 min"},
    "speed":      {"x": 52,  "y": 232, "kind": "statement", "label": "1.6 m/s"},
    "stopping":   {"x": 196, "y": 243, "kind": "statement", "label": "0.85 m"},
    "adr_11":     {"x": 336, "y": 62,  "kind": "document", "label": "ADR 0011"},
    "adr_07":     {"x": 404, "y": 158, "kind": "document", "label": "ADR 0007"},
    "adr_04":     {"x": 332, "y": 254, "kind": "document", "label": "ADR 0004"},
    "written":    {"x": 140, "y": 318, "kind": "statement", "label": "new"},
}

GRAPH_EDGES = [
    ("swap", "fact_doc", ""), ("charge", "fact_doc", ""),
    ("speed", "fact_doc", ""), ("stopping", "fact_doc", ""),
    ("fact_doc", "adr_07", "relates_to"),
    ("adr_11", "adr_07", "supersedes"), ("adr_07", "adr_04", "supersedes"),
    ("written", "fact_doc", ""),
]

FIRST_NODES = ["fact_doc", "swap", "charge", "speed", "stopping", "adr_11", "adr_07", "adr_04"]
NEIGHBOURS_OF_SWAP = ["fact_doc", "charge"]
LINEAGE_EDGES = [("adr_11", "adr_07"), ("adr_07", "adr_04")]


def draw_graph(visible_nodes, lit_node="", neighbour_nodes=(), lit_edges=(), chip="",
               drawn_edges=True):
    """Return the SVG for one state of the map.

    visible_nodes decides what exists yet (the map being built), lit_node is the statement
    the question matched, neighbour_nodes are the ones that came back with it, and lit_edges
    are the relations a path ran through.
    """
    pieces = ['<svg viewBox="0 0 470 360" width="470" height="360" xmlns="http://www.w3.org/2000/svg">',
              '<defs><marker id="tip" markerWidth="8" markerHeight="8" refX="7" refY="4"'
              ' orient="auto"><path d="M0 0 L8 4 L0 8 z" fill="#f0a6ff"/></marker></defs>']

    for source, target, relation in GRAPH_EDGES:
        if not drawn_edges or source not in visible_nodes or target not in visible_nodes:
            continue
        start, end = GRAPH_NODES[source], GRAPH_NODES[target]
        is_lit = (source, target) in lit_edges
        colour = "#f0a6ff" if is_lit else ("#3d5891" if relation else "#28355a")
        arrow = " marker-end='url(#tip)'" if is_lit else ""
        pieces.append(f'<line x1="{start["x"]}" y1="{start["y"]}" x2="{end["x"]}" y2="{end["y"]}"'
                      f' stroke="{colour}" stroke-width="{3 if is_lit else 1.6}"'
                      f'{arrow}/>')
        if is_lit and relation:
            # Sit the relation word beside the edge, not on top of the node labels: step off
            # the line along its perpendicular.
            span_x, span_y = end["x"] - start["x"], end["y"] - start["y"]
            length = max((span_x ** 2 + span_y ** 2) ** 0.5, 1)
            label_x = (start["x"] + end["x"]) / 2 - span_y / length * 34
            label_y = (start["y"] + end["y"]) / 2 + span_x / length * 34
            pieces.append(f'<text x="{label_x}" y="{label_y}" fill="#f0a6ff" font-size="11"'
                          f' font-family="monospace" text-anchor="middle">{relation}</text>')

    for name, node in GRAPH_NODES.items():
        if name not in visible_nodes:
            continue
        is_lit_node = name == lit_node
        halo_colour = "#ffd479" if is_lit_node else "#5eead4"
        if is_lit_node or name in neighbour_nodes:
            halo_radius = 34 if node["kind"] == "document" else 28
            pieces.append(f'<circle cx="{node["x"]}" cy="{node["y"]}" r="{halo_radius}"'
                          f' fill="{halo_colour}" opacity="{0.20 if is_lit_node else 0.13}"/>')
        if node["kind"] == "document":
            pieces.append(f'<circle cx="{node["x"]}" cy="{node["y"]}" r="20" fill="#1b2a52"'
                          f' stroke="{"#ffd479" if is_lit_node else "#5478c4"}" stroke-width="2"/>')
            pieces.append(f'<text x="{node["x"]}" y="{node["y"] + 4}" fill="#c8d3ea" font-size="11"'
                          f' font-family="monospace" text-anchor="middle">md</text>')
            pieces.append(f'<text x="{node["x"]}" y="{node["y"] + 36}" fill="#c8d3ea" font-size="11.5"'
                          f' font-family="monospace" text-anchor="middle">{node["label"]}</text>')
        else:
            # A statement is drawn as a pill holding the value it carries, so that a first
            # look tells the two kinds of node apart without reading a legend.
            width = 15 + 8 * len(node["label"])
            pieces.append(f'<rect x="{node["x"] - width / 2}" y="{node["y"] - 13}" width="{width}"'
                          f' height="26" rx="13" fill="{"#ffd479" if is_lit_node else "#22304f"}"'
                          f' stroke="{"#ffd479" if is_lit_node else "#41598f"}" stroke-width="2"/>')
            pieces.append(f'<text x="{node["x"]}" y="{node["y"] + 4}"'
                          f' fill="{"#0b1020" if is_lit_node else "#a9bde6"}" font-size="11.5"'
                          f' font-family="monospace" text-anchor="middle">{node["label"]}</text>')

    pieces.append('<g opacity="0.9"><circle cx="214" cy="348" r="7" fill="#1b2a52" stroke="#5478c4"'
                  ' stroke-width="1.5"/>'
                  '<text x="228" y="352" fill="#7f8dad" font-size="10.5"'
                  ' font-family="monospace">a document</text>'
                  '<rect x="326" y="340" width="16" height="16" rx="8" fill="#22304f"'
                  ' stroke="#41598f" stroke-width="1.5"/>'
                  '<text x="348" y="352" fill="#7f8dad" font-size="10.5"'
                  ' font-family="monospace">a statement in it</text></g>')

    if chip:
        pieces.append('<rect x="8" y="8" width="300" height="26" rx="8" fill="#141d33"'
                      ' stroke="#3d5891"/>')
        pieces.append(f'<text x="20" y="26" fill="#8fa3cc" font-size="12"'
                      f' font-family="monospace">{chip}</text>')
    pieces.append("</svg>")
    return "\n".join(pieces)


# ---------------------------------------------------------------- the session on the left

# What a person actually does is ask Claude Code a question in their own words. Calling
# ask.py is the plugin's own business, so it is shown the way the session shows it: as the
# skill's tool line under the question.
QUESTION = "what was the battery swap threshold again?"
SKILL_CALL = ['<span class="tool">● context-graph</span>',
              '<span class="tool">  ⎿ python ask.py "battery swap threshold"</span>']
TOOL_OUTPUT = ('<span class="tool">    NODE Swap threshold: a robot returns to a dock below'
               ' 18% state of charge. [loc=10]</span>')
REPLY = ('<span class="say">●</span> Below <span class="v">18% state of charge</span> — '
         '<span class="loc">Warehouse Robot Fleet.md:10</span>')

PATH_QUESTION = "and which decision replaced ADR 0004?"
PATH_CALL = ['<span class="tool">● context-graph</span>',
             '<span class="tool">  ⎿ python ask.py --path "ADR 0011" "ADR 0004"</span>']
PATH_REPLY = ('<span class="say">●</span> ADR 0011 <span class="rel">superseded</span> ADR 0007,'
              ' which <span class="rel">superseded</span> ADR 0004.')

COMPACTING = '<span class="dim">[context is nearly full — compacting the conversation]</span>'
WRITING = '<span class="tool">  ⎿ writing this session into your notes</span>'
REBUILT = '<span class="ok">  ⎿ map rebuilt · nodes 32 · links 33 · 0.00s</span>'


def asked_line(typed, cursor=True):
    """The question line as the session shows it, with the block cursor while it is typed."""
    return ('<span class="p">&gt;</span> <span class="c">' + html.escape(typed) + "</span>"
            + ('<span class="cur">&nbsp;</span>' if cursor else ""))


def typing_frames(question, keystrokes_per_frame=3):
    """The question appearing a few characters at a time."""
    return [question[:count] for count in
            range(0, len(question) + keystrokes_per_frame, keystrokes_per_frame)][1:] + [question]


def build_storyboard():
    """Return (session html, graph svg, caption, milliseconds) for every frame, in order."""
    frames = []
    everything = set(FIRST_NODES)

    # 1. the map appears: documents first, then the statements under them, then the links
    for count in (1, 3, 5, 8):
        frames.append(("", draw_graph(set(FIRST_NODES[:count]), drawn_edges=False),
                       "Every heading and every statement in your notes becomes a node.", 260))
    frames.append(("", draw_graph(everything),
                   "The links you wrote by hand — <b>supersedes</b>, <b>relates_to</b> — become "
                   "the edges. No model is asked to guess them.", 1500))

    # 2. a question in your own words
    frames.append((asked_line(""), draw_graph(everything),
                   "You ask Claude Code the way you always do.", 700))
    for typed in typing_frames(QUESTION):
        frames.append((asked_line(typed), draw_graph(everything),
                       "You ask Claude Code the way you always do.", 45))

    asked = asked_line(QUESTION, cursor=False)
    called = asked + "\n\n" + "\n".join(SKILL_CALL)
    frames.append((called, draw_graph(everything),
                   "The skill turns the question into a lookup on the map — that is the "
                   "<b>ask.py</b> line.", 800))
    frames.append((called, draw_graph(everything, lit_node="swap"),
                   "The statement that matches lights up.", 500))
    frames.append((called, draw_graph(everything, lit_node="swap",
                                      neighbour_nodes=NEIGHBOURS_OF_SWAP),
                   "The nodes around it come back with it — the document it sits in, and its "
                   "neighbours.", 800))
    answered = called + "\n" + TOOL_OUTPUT + "\n\n" + REPLY
    frames.append((answered, draw_graph(everything, lit_node="swap",
                                        neighbour_nodes=NEIGHBOURS_OF_SWAP,
                                        chip=r"notes\facts\Warehouse Robot Fleet.md  loc=10"),
                   "You get the sentence itself, and the file and line it sits on. No file was "
                   "opened.", 2800))

    # 3. the lineage
    for typed in typing_frames(PATH_QUESTION):
        frames.append((answered + "\n\n" + asked_line(typed), draw_graph(everything),
                       "Ask how two decisions are related.", 45))
    path_asked = (answered + "\n\n" + asked_line(PATH_QUESTION, cursor=False)
                  + "\n\n" + "\n".join(PATH_CALL))
    frames.append((path_asked, draw_graph(everything, lit_edges=[LINEAGE_EDGES[0]]),
                   "It walks the relation words someone typed.", 500))
    walked_graph = draw_graph(everything, lit_edges=LINEAGE_EDGES)
    frames.append((path_asked, walked_graph,
                   "It walks the relation words someone typed.", 400))
    frames.append((path_asked + "\n\n" + PATH_REPLY, walked_graph,
                   "Which decision replaced which, in the order it happened.", 2600))

    # 4. the refresh, which nobody has to ask for
    conversation = path_asked + "\n\n" + PATH_REPLY
    compacting = conversation + "\n\n" + COMPACTING + "\n" + WRITING
    frames.append((compacting, draw_graph(everything | {"written"}, lit_node="written"),
                   "When the conversation is compacted, the session is written back into your "
                   "notes...", 1700))
    frames.append((compacting + "\n" + REBUILT,
                   draw_graph(everything | {"written"},
                              neighbour_nodes=["written", "fact_doc"]),
                   "...and the map is rebuilt, so your next question already finds it.", 3000))
    return frames


PAGE_TEMPLATE = """<!doctype html>
<html><head><meta charset="utf-8"><style>
  html,body{{margin:0;padding:0;background:#0b1020;}}
  .wrap{{width:1060px;height:470px;box-sizing:border-box;padding:20px;display:flex;gap:16px;}}
  .term,.map{{background:#0f1629;border:1px solid #24304d;border-radius:11px;overflow:hidden;}}
  .term{{width:552px;}} .map{{flex:1;display:flex;flex-direction:column;}}
  .bar{{display:flex;align-items:center;gap:7px;padding:9px 13px;background:#141d33;
       border-bottom:1px solid #24304d;color:#7f8dad;
       font:12px/1 ui-sans-serif,system-ui,"Segoe UI",sans-serif;}}
  .dot{{width:9px;height:9px;border-radius:50%;}}
  .r{{background:#ff5f57}}.y{{background:#febc2e}}.g{{background:#28c840}}
  .bar .name{{margin-left:8px;}}
  pre{{margin:0;padding:15px 16px;color:#c8d3ea;
      font:13px/1.5 "Cascadia Mono","JetBrains Mono",Consolas,monospace;
      white-space:pre-wrap;word-break:break-word;}}
  .p{{color:#5eead4;font-weight:700}} .c{{color:#e6edff;font-weight:600}} .k{{color:#8ab4ff}}
  .v{{color:#ffd479}} .loc{{color:#7f8dad}} .rel{{color:#f0a6ff}} .dim{{color:#66748f}}
  .ok{{color:#57d38c}} .cur{{background:#5eead4;color:#5eead4;}}
  .tool{{color:#66748f}} .say{{color:#57d38c;font-weight:700}}
  .stage{{flex:1;display:flex;align-items:center;justify-content:center;}}
  .caption{{padding:0 14px 12px;color:#8fa3cc;text-align:center;
           font:12.5px/1.45 ui-sans-serif,system-ui,"Segoe UI",sans-serif;}}
  .caption b{{color:#e6edff;font-weight:600;}}
</style></head>
<body><div class="wrap">
  <div class="term">
    <div class="bar"><span class="dot r"></span><span class="dot y"></span><span class="dot g"></span>
      <span class="name">Claude Code</span></div>
<pre>{terminal}</pre></div>
  <div class="map">
    <div class="bar"><span class="name">the map, built from your notes</span></div>
    <div class="stage">{graph}</div>
    <div class="caption">{caption}</div>
  </div>
</div></body></html>
"""


def render(frames):
    """Screenshot every frame with headless Chrome. Returns the file paths, in order."""
    os.makedirs(FRAME_DIR, exist_ok=True)
    paths = []
    for index, (terminal, graph, caption, _duration) in enumerate(frames):
        page_path = os.path.join(FRAME_DIR, f"frame_{index:03d}.html")
        image_path = os.path.join(FRAME_DIR, f"frame_{index:03d}.png")
        with open(page_path, "w", encoding="utf-8") as handle:
            handle.write(PAGE_TEMPLATE.format(terminal=terminal, graph=graph, caption=caption))
        subprocess.run([CHROME, "--headless", "--disable-gpu", "--hide-scrollbars",
                        f"--window-size={WIDTH},{HEIGHT}",
                        f"--screenshot={image_path}", "file:///" + page_path.replace("\\", "/")],
                       check=True, capture_output=True)
        paths.append(image_path)
        print(f"frame {index + 1}/{len(frames)}", end="\r", flush=True)
    return paths


def assemble(image_paths, durations, gif_path):
    """Stitch the frames into one looping GIF, each frame keeping its own duration."""
    images = [Image.open(path).convert("RGB") for path in image_paths]
    palette = images[-1].quantize(colors=128, method=Image.MEDIANCUT)
    frames = [image.quantize(palette=palette, dither=Image.Dither.NONE) for image in images]
    frames[0].save(gif_path, save_all=True, append_images=frames[1:], loop=0,
                   duration=durations, optimize=True, disposal=2)
    return os.path.getsize(gif_path)


def main():
    storyboard = build_storyboard()
    image_paths = render(storyboard)
    gif_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(OUTPUT_DIR, "demo.gif")
    size = assemble(image_paths, [frame[-1] for frame in storyboard], gif_path)
    print(f"\n{gif_path} - {len(storyboard)} frames, {size / 1_000_000:.2f} MB")


if __name__ == "__main__":
    main()
