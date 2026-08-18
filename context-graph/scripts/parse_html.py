"""Turns one HTML document into the same shape of pieces the markdown parser produces.

Images, styling and scripts are dropped, but text inside SVG is kept: the point
a diagram makes usually lives in that text.
"""
from html.parser import HTMLParser

HEADING_TAGS = {"h1", "h2", "h3"}
TEXT_TAGS = {"p", "li", "td", "th", "text", "title"}
DROP_TAGS = {"style", "script"}


class _Collector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.sections, self.statements, self.links = [], [], []
        self.current_section = ""
        self._open_tag = None
        self._buffer = []
        self._buffer_line = 0
        self._dropping = False

    def handle_starttag(self, tag, attributes):
        if tag in DROP_TAGS:
            self._dropping = True
            return
        if tag == "a":
            for name, value in attributes:
                if name == "href" and value:
                    self.links.append({"target": value.strip(), "relation": None,
                                       "line": self.getpos()[0]})
        if tag in HEADING_TAGS or tag in TEXT_TAGS:
            self._open_tag = tag
            self._buffer = []
            self._buffer_line = self.getpos()[0]

    def handle_data(self, data):
        if not self._dropping and self._open_tag:
            self._buffer.append(data)

    def handle_endtag(self, tag):
        if tag in DROP_TAGS:
            self._dropping = False
            return
        if tag != self._open_tag:
            return
        content = " ".join("".join(self._buffer).split())
        if content:
            if tag in HEADING_TAGS:
                self.current_section = content
                self.sections.append({"title": content, "line": self._buffer_line, "body": ""})
            else:
                self.statements.append({"text": content, "line": self._buffer_line,
                                        "section": self.current_section})
                if self.sections:
                    self.sections[-1]["body"] += content + "\n"
        self._open_tag = None
        self._buffer = []


def parse_html(text):
    """Scan one document and return its pieces. Line numbers are real lines in the source file."""
    collector = _Collector()
    collector.feed(text)
    return {"sections": collector.sections,
            "statements": collector.statements,
            "links": collector.links}
