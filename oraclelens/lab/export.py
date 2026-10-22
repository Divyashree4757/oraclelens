"""Write a static, self-contained results dashboard (no server needed).

    python -m oraclelens.lab.export --results results --out docs

The output `docs/index.html` can be opened directly or served by GitHub Pages
(Settings → Pages → deploy from branch `main`, folder `/docs`).
The live lab tab is disabled in this mode and explains how to run it locally.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .bundle import build_bundle
from .page import render_page


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Export the static OracleLens dashboard.")
    ap.add_argument("--results", default="results")
    ap.add_argument("--out", default="docs")
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    page = render_page(build_bundle(args.results), live=False)
    (out / "index.html").write_text(page)
    (out / ".nojekyll").write_text("")
    print(f"wrote {out / 'index.html'} ({len(page) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
