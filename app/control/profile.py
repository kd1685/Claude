"""UI calibration profile + macro engine for the ADB backend.

Rise of Kingdoms has no API, so we drive the UI by tapping fixed screen
coordinates. Those coordinates depend on the client's resolution, so they live
in a JSON *profile* (see app/profiles/rok_720p.json) that you calibrate once
for your emulator. A macro is just an ordered list of steps; the engine
substitutes `{placeholders}` (e.g. the governor name) before running each step.

Step types:
    {"tap":   "anchor" | [x, y]}
    {"swipe": "anchor" | [x1, y1, x2, y2, ms]}
    {"text":  "template string with {vars}"}
    {"key":   <android keycode int>}          # 4=back, 66=enter
    {"wait":  <milliseconds>}
    {"ocr":   {"region": [x, y, w, h], "into": "var", "pattern": "regex"}}
"""
from __future__ import annotations

import json
import re
from pathlib import Path


class UIProfile:
    def __init__(self, data: dict):
        self.data = data
        self.screen = data.get("screen", {"width": 1280, "height": 720})
        self.anchors: dict[str, list[int]] = data.get("anchors", {})
        self.macros: dict[str, list[dict]] = data.get("macros", {})
        self.rankings: dict = data.get("rankings", {})

    @classmethod
    def load(cls, path: str | Path) -> "UIProfile":
        return cls(json.loads(Path(path).read_text()))

    def point(self, ref) -> tuple[int, int]:
        """Resolve an anchor name or [x, y] to absolute coordinates."""
        if isinstance(ref, str):
            ref = self.anchors[ref]
        return int(ref[0]), int(ref[1])

    def macro(self, name: str) -> list[dict]:
        if name not in self.macros:
            raise KeyError(f"macro '{name}' not defined in profile")
        return self.macros[name]


def render(template: str, ctx: dict) -> str:
    """Substitute {vars} from ctx into a template (missing -> empty)."""
    def repl(m: re.Match) -> str:
        return str(ctx.get(m.group(1), ""))
    return re.sub(r"\{(\w+)\}", repl, template)
