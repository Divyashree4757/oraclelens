"""Assemble the single-page dashboard from static assets.

The same page runs in two modes:
  * live: served by the lab server, fetches /api/results and can run simulations
  * static: data inlined, no server needed (GitHub Pages, sharing a file)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

STATIC = Path(__file__).parent / "static"


def render_page(data: Optional[dict], live: bool) -> str:
    html = (STATIC / "index.html").read_text()
    css = (STATIC / "app.css").read_text()
    js = (STATIC / "app.js").read_text()
    boot = {"live": live, "data": data}
    # </ is escaped so inlined JSON can never close the script tag.
    boot_json = json.dumps(boot, separators=(",", ":")).replace("</", "<\\/")
    return (html.replace("/*__CSS__*/", css)
                .replace("/*__BOOT__*/", f"window.OL_BOOT = {boot_json};")
                .replace("/*__JS__*/", js))
