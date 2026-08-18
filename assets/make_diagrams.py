"""Generate the README diagrams as SVG, one light and one dark variant each.

The two variants differ only by palette, so the shapes are written once here and
rendered twice. Run this whenever a diagram changes:

    python assets/make_diagrams.py
"""
import io
import os

ASSETS_DIR = os.path.dirname(os.path.abspath(__file__))

LIGHT = {
    "bg": "#ffffff", "panel": "#f8fafc", "panel_line": "#e2e8f0",
    "ink": "#0f172a", "muted": "#64748b",
    "accent": "#4338ca", "accent_bg": "#eef2ff", "accent_line": "#a5b4fc",
    "good": "#047857", "good_bg": "#ecfdf5", "good_line": "#6ee7b7",
    "bad": "#b91c1c", "bad_bg": "#fef2f2", "bad_line": "#fca5a5",
    "arrow": "#94a3b8",
}
DARK = {
    "bg": "#0d1117", "panel": "#161b22", "panel_line": "#30363d",
    "ink": "#e6edf3", "muted": "#8b949e",
    "accent": "#a5b4fc", "accent_bg": "#1e1b4b", "accent_line": "#4338ca",
    "good": "#6ee7b7", "good_bg": "#052e23", "good_line": "#047857",
    "bad": "#fca5a5", "bad_bg": "#3b0d0d", "bad_line": "#b91c1c",
    "arrow": "#6e7681",
}

FONT = "ui-sans-serif, -apple-system, 'Segoe UI', Roboto, sans-serif"
MONO = "ui-monospace, SFMono-Regular, Consolas, monospace"


def box(x, y, w, h, fill, stroke, radius=8, stroke_width=1):
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{stroke_width}"/>')


def text(x, y, content, size=12, fill="#0f172a", weight="400",
         anchor="start", family=FONT):
    return (f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" '
            f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}">{content}</text>')


def arrow(x1, y1, x2, y2, color, marker="arrow"):
    return (f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" '
            f'stroke-width="1.6" marker-end="url(#{marker})"/>')


def header(width, height, palette, markers=("arrow", "arrow_accent", "arrow_good")):
    marker_colors = {"arrow": palette["arrow"], "arrow_accent": palette["accent"],
                     "arrow_good": palette["good"]}
    defs = "".join(
        f'<marker id="{name}" markerWidth="9" markerHeight="9" refX="8" refY="4.5" '
        f'orient="auto"><path d="M0,0 L9,4.5 L0,9 z" fill="{marker_colors[name]}"/></marker>'
        for name in markers)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" role="img">'
            f'<defs>{defs}</defs>'
            f'<rect width="{width}" height="{height}" rx="10" fill="{palette["bg"]}"/>')


def structure_diagram(palette):
    """What the map is built from, and what it answers."""
    parts = [header(880, 300, palette)]
    add = parts.append

    add(box(16, 40, 224, 200, palette["panel"], palette["panel_line"], 10))
    add(text(128, 66, "Your documents", 13, palette["ink"], "600", "middle"))
    add(text(128, 84, "markdown and HTML", 10.5, palette["muted"], "400", "middle"))

    add(box(30, 98, 196, 56, palette["bg"], palette["panel_line"], 6))
    add(text(42, 118, "Statements", 11.5, palette["ink"], "600"))
    add(text(42, 136, "the figures live here", 10.5, palette["muted"]))

    add(box(30, 164, 196, 56, palette["bg"], palette["panel_line"], 6))
    add(text(42, 184, "Relations you wrote", 11.5, palette["ink"], "600"))
    add(text(42, 202, "- supersedes [[...]]", 10, palette["muted"], "400", "start", MONO))

    add(arrow(246, 140, 288, 140, palette["good"], "arrow_good"))
    add(text(267, 132, "copy", 9.5, palette["good"], "600", "middle"))

    add(box(294, 62, 210, 156, palette["good_bg"], palette["good_line"], 10, 1.5))
    add(text(399, 88, "Copy, do not guess", 13, palette["ink"], "600", "middle"))
    add(text(399, 112, "statement -&gt; node, verbatim", 10.5, palette["muted"], "400", "middle"))
    add(text(399, 130, "relation -&gt; link, same name", 10.5, palette["muted"], "400", "middle"))
    add(text(399, 148, "file and line kept on every node", 10.5, palette["muted"], "400", "middle"))
    add(text(399, 176, "no language model", 12, palette["good"], "600", "middle"))
    add(text(399, 196, "0.10 s for 175 documents", 11.5, palette["ink"], "600", "middle"))

    add(arrow(510, 140, 552, 140, palette["accent"], "arrow_accent"))

    add(box(558, 40, 306, 152, palette["accent_bg"], palette["accent_line"], 10, 1.5))
    add(text(711, 66, "One map, three answers", 13, palette["ink"], "600", "middle"))
    add(box(574, 78, 274, 32, palette["bg"], palette["panel_line"], 6))
    add(text(586, 98, "Value  —  the statement, plus file:line", 11, palette["ink"]))
    add(box(574, 114, 274, 32, palette["bg"], palette["panel_line"], 6))
    add(text(586, 134, "Connection  —  what touches what", 11, palette["ink"]))
    add(box(574, 150, 274, 32, palette["bg"], palette["panel_line"], 6))
    add(text(586, 170, "Lineage  —  what superseded what", 11, palette["ink"]))

    add(arrow(711, 198, 711, 224, palette["accent"], "arrow_accent"))
    add(box(558, 230, 306, 52, palette["bg"], palette["accent_line"], 10))
    add(text(711, 252, "Open only the line it cites", 12.5, palette["ink"], "600", "middle"))
    add(text(711, 270, "never the whole file", 11, palette["good"], "600", "middle"))

    add(text(16, 268, "Documents are read, never written to.", 10.5, palette["muted"]))
    parts.append("</svg>")
    return "".join(parts)


def flow_diagram(palette):
    """A question turning into an answer, and when the map is rebuilt."""
    parts = [header(880, 330, palette)]
    add = parts.append

    add(box(16, 34, 150, 58, palette["panel"], palette["panel_line"]))
    add(text(91, 58, "A question", 12.5, palette["ink"], "600", "middle"))
    add(text(91, 76, "what was that figure?", 10.5, palette["muted"], "400", "middle"))
    add(arrow(170, 63, 206, 63, palette["accent"], "arrow_accent"))

    add(box(212, 26, 176, 74, palette["accent_bg"], palette["accent_line"]))
    add(text(300, 50, "Ask the map", 12.5, palette["ink"], "600", "middle"))
    add(text(300, 68, "in the language the", 10.5, palette["muted"], "400", "middle"))
    add(text(300, 84, "documents are written in", 10.5, palette["muted"], "400", "middle"))
    add(arrow(392, 63, 428, 63, palette["accent"], "arrow_accent"))

    add(box(434, 26, 206, 74, palette["good_bg"], palette["good_line"]))
    add(text(537, 50, "The answer", 12.5, palette["ink"], "600", "middle"))
    add(text(537, 70, "the statement, and file:line", 10.5, palette["muted"], "400", "middle"))
    add(text(537, 90, "usually the end of it", 11, palette["good"], "600", "middle"))

    add(arrow(644, 63, 680, 63, palette["good"], "arrow_good"))
    add(box(686, 34, 178, 58, palette["panel"], palette["panel_line"]))
    add(text(775, 58, "Answer, with the source", 11.5, palette["ink"], "600", "middle"))
    add(text(775, 76, "a few hundred characters", 10.5, palette["muted"], "400", "middle"))

    add(f'<path d="M537,104 L537,126" stroke="{palette["arrow"]}" stroke-width="1.4" '
        f'stroke-dasharray="4 3" marker-end="url(#arrow)"/>')
    add(box(434, 132, 206, 48, palette["bg"], palette["panel_line"]))
    add(text(537, 152, "Need more? open those lines", 11, palette["ink"], "600", "middle"))
    add(text(537, 170, "three or more places: delegate", 10.5, palette["muted"], "400", "middle"))

    add(f'<line x1="16" y1="204" x2="864" y2="204" stroke="{palette["panel_line"]}"/>')
    add(text(16, 228, "The map is rebuilt at four points, never on a question",
             12, palette["ink"], "600"))

    labels = ["session starts", "delegated work ends", "just before compaction", "just after"]
    for index, label in enumerate(labels):
        x = 16 + index * 214
        add(box(x, 240, 198, 46, palette["panel"], palette["panel_line"]))
        add(text(x + 99, 262, label, 11, palette["ink"], "600", "middle"))
        add(text(x + 99, 279, "0.10 s" if index != 2 else "writes the session down",
                 10, palette["muted"], "400", "middle"))

    add(text(16, 312, "In between it says how far behind it is, in 3 ms, and answers anyway.",
             10.5, palette["muted"]))
    parts.append("</svg>")
    return "".join(parts)


def main():
    diagrams = {"structure": structure_diagram, "flow": flow_diagram}
    for name, build in diagrams.items():
        for theme, palette in (("light", LIGHT), ("dark", DARK)):
            path = os.path.join(ASSETS_DIR, f"{name}-{theme}.svg")
            io.open(path, "w", encoding="utf-8").write(build(palette))
            print("wrote", os.path.basename(path))


if __name__ == "__main__":
    main()
