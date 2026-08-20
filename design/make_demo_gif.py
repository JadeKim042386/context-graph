"""Builds the readme's hero animation: a terminal asking the map and getting the line back.

Every frame is one HTML page rendered by headless Chrome, and the frames are stitched into a
GIF with per-frame durations, so typing runs fast and the answers stay up long enough to read.
The transcript is copied from a real run against the sample documents in scratchpad/demo.
"""
import html
import os
import subprocess
import sys

from PIL import Image

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
FRAME_DIR = os.path.join(OUTPUT_DIR, "frames")
WIDTH, HEIGHT = 960, 430

PAGE_TEMPLATE = """<!doctype html>
<html><head><meta charset="utf-8"><style>
  html,body{{margin:0;padding:0;background:#0b1020;}}
  .wrap{{width:960px;height:430px;box-sizing:border-box;padding:22px;}}
  .term{{height:386px;background:#0f1629;border:1px solid #24304d;border-radius:11px;
        overflow:hidden;box-shadow:0 14px 36px rgba(0,0,0,.45);}}
  .bar{{display:flex;align-items:center;gap:7px;padding:10px 14px;background:#141d33;
       border-bottom:1px solid #24304d;}}
  .dot{{width:10px;height:10px;border-radius:50%;}}
  .r{{background:#ff5f57}}.y{{background:#febc2e}}.g{{background:#28c840}}
  .title{{margin-left:9px;color:#7f8dad;font:12px/1 ui-sans-serif,system-ui,"Segoe UI",sans-serif;}}
  pre{{margin:0;padding:16px 18px;color:#c8d3ea;
      font:13.5px/1.55 "Cascadia Mono","JetBrains Mono",Consolas,monospace;
      white-space:pre-wrap;word-break:break-word;}}
  .p{{color:#5eead4}} .c{{color:#e6edff;font-weight:600}} .k{{color:#8ab4ff}}
  .v{{color:#ffd479}} .loc{{color:#7f8dad}} .rel{{color:#f0a6ff}} .dim{{color:#66748f}}
  .cur{{background:#5eead4;color:#5eead4;}}
</style></head>
<body><div class="wrap"><div class="term">
  <div class="bar"><span class="dot r"></span><span class="dot y"></span><span class="dot g"></span>
    <span class="title">context-graph &mdash; ask your notes, get the line</span></div>
<pre>{body}</pre></div></div></body></html>
"""

COMMENT = '<span class="dim"># the sentence you need is somewhere in 289,000 characters of notes</span>'
QUESTION = 'python ask.py "battery swap threshold state of charge"'
ANSWER = [
    '<span class="k">NODE</span> <span class="v">Swap threshold: a robot returns to a dock below 18% state of charge.</span>',
    '     <span class="loc">[src=notes\\facts\\Warehouse Robot Fleet - Facts.md loc=10]</span>',
    '<span class="k">NODE</span> <span class="v">Charge cycle: full charge takes 42 min, and a robot runs 5.4 h on it.</span>',
    '     <span class="loc">[src=notes\\facts\\Warehouse Robot Fleet - Facts.md loc=9]</span>',
]
PATH_QUESTION = ('python ask.py --path "ADR 0011 Charge To 80 Percent At Peak" '
                 '"ADR 0004 One Dock Per Aisle"')
PATH_ANSWER = [
    'Shortest path (2 hops):',
    '  ADR 0011 Charge To 80 Percent At Peak <span class="rel">--supersedes--&gt;</span>'
    ' ADR 0007 Dock Assignment by Aisle Distance <span class="rel">--supersedes--&gt;</span>'
    ' ADR 0004 One Dock Per Aisle',
]
CLOSING = ('<span class="dim">the statement itself, and the file and line it sits on. '
           'no model call, 0.1 s to rebuild 175 documents.</span>')


def prompt_line(typed, cursor=True):
    """One shell line, optionally with the block cursor sitting after what has been typed."""
    return ('<span class="p">$</span> <span class="c">' + html.escape(typed) + "</span>"
            + ('<span class="cur">&nbsp;</span>' if cursor else ""))


def typing_frames(command, keystrokes_per_frame=4):
    """The command appearing a few characters at a time."""
    return [command[:count] for count in
            range(0, len(command) + keystrokes_per_frame, keystrokes_per_frame)][1:] + [command]


def build_storyboard():
    """Return (html body, milliseconds) for every frame, in order."""
    frames = [(COMMENT + "\n" + prompt_line(""), 1100)]

    typed_so_far = []
    for typed in typing_frames(QUESTION):
        typed_so_far = [COMMENT, prompt_line(typed)]
        frames.append(("\n".join(typed_so_far), 45))

    asked = COMMENT + "\n" + prompt_line(QUESTION, cursor=False)
    frames.append((asked, 320))
    frames.append((asked + "\n" + "\n".join(ANSWER[:2]), 500))
    answered = asked + "\n" + "\n".join(ANSWER)
    frames.append((answered, 2400))

    for typed in typing_frames(PATH_QUESTION):
        frames.append((answered + "\n\n" + prompt_line(typed), 45))

    path_asked = answered + "\n\n" + prompt_line(PATH_QUESTION, cursor=False)
    frames.append((path_asked, 320))
    frames.append((path_asked + "\n" + PATH_ANSWER[0], 260))
    walked = path_asked + "\n" + "\n".join(PATH_ANSWER)
    frames.append((walked, 2000))
    frames.append((walked + "\n\n" + CLOSING, 3200))
    return frames


def render(frames):
    """Screenshot every frame with headless Chrome. Returns the file paths, in order."""
    os.makedirs(FRAME_DIR, exist_ok=True)
    paths = []
    for index, (body, _duration) in enumerate(frames):
        page_path = os.path.join(FRAME_DIR, f"frame_{index:03d}.html")
        image_path = os.path.join(FRAME_DIR, f"frame_{index:03d}.png")
        with open(page_path, "w", encoding="utf-8") as handle:
            handle.write(PAGE_TEMPLATE.format(body=body))
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
    size = assemble(image_paths, [duration for _body, duration in storyboard], gif_path)
    print(f"\n{gif_path} - {len(storyboard)} frames, {size / 1_000_000:.2f} MB")


if __name__ == "__main__":
    main()
