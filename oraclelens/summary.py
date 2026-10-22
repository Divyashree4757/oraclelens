"""Collect every sweep's breaking points into one table.

    python -m oraclelens.summary --results results

Writes results/breaking_points.md and results/breaking_points.csv.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def _missing(v) -> bool:
    return v is None or (isinstance(v, float) and v != v)


def _fmt(b: dict) -> str:
    if _missing(b["breaking_point"]):
        return "never"
    p, lo, hi = b["breaking_point"], b["ci_low"], b["ci_high"]
    if _missing(lo) or (abs(lo - p) < 1e-9 and abs(hi - p) < 1e-9):
        return f"{p:.0%}"
    return f"{p:.0%} [{lo:.0%}–{hi:.0%}]"


def collect(results: Path) -> pd.DataFrame:
    rows = []
    for f in sorted(results.glob("bp_*/summary.json")):
        s = json.loads(f.read_text())
        for tol, bps in s["breaking_points"].items():
            for agg, b in bps.items():
                rows.append({"sweep": s["name"], "tolerance": float(tol), "aggregator": agg,
                             "seeds": s["seeds"], **b})
    return pd.DataFrame(rows)


def to_markdown(df: pd.DataFrame, tol: float) -> str:
    d = df[df["tolerance"] == tol]
    aggs = list(dict.fromkeys(d["aggregator"]))
    lines = [f"### Tolerance {tol:.1%}", "",
             "| Sweep | " + " | ".join(a.replace("_", " ") for a in aggs) + " |",
             "| --- |" + " --- |" * len(aggs)]
    for sweep, g in d.groupby("sweep", sort=True):
        by = {r["aggregator"]: r for r in g.to_dict("records")}
        lines.append(f"| {sweep} | " + " | ".join(_fmt(by[a]) for a in aggs) + " |")
    return "\n".join(lines)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Summarize breaking points across sweeps.")
    ap.add_argument("--results", default="results")
    args = ap.parse_args(argv)
    results = Path(args.results)
    df = collect(results)
    df.to_csv(results / "breaking_points.csv", index=False)
    parts = ["# Breaking points", "",
             "Smallest share of faulty nodes at which P(round error > tolerance) exceeds 5%, "
             "with a 95% bootstrap interval over seeds where it is not a single value. "
             "\"never\" means not reached within the sweep.", ""]
    for tol in sorted(df["tolerance"].unique()):
        parts += [to_markdown(df, tol), ""]
    (results / "breaking_points.md").write_text("\n".join(parts))
    print("\n".join(parts))


if __name__ == "__main__":
    main()
