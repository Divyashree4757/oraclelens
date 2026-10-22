"""Collect generated results into one JSON-serializable bundle for the dashboard."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd

from .. import CAUSES, INSUFFICIENT, __version__


def clean(obj):
    """Make an object JSON-safe: NaN/inf -> None, numpy -> python."""
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if hasattr(obj, "item") and not isinstance(obj, (str, bytes)):
        obj = obj.item()
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    return obj


def _sweep(d: Path) -> dict:
    cfg = json.loads((d / "config.json").read_text())
    summary = json.loads((d / "summary.json").read_text())
    curves = {}
    for f in sorted(d.glob("curves_tol*.csv")):
        tol = f.stem.replace("curves_tol", "")
        df = pd.read_csv(f)
        curves[tol] = {agg: {c: g[c].round(5).tolist() for c in
                             ("fraction", "fail_prob", "ci_low", "ci_high")}
                       for agg, g in df.groupby("aggregator", sort=False)}
    availability = {}
    raw = d / "sweep_raw.parquet"
    if raw.exists():
        df = pd.read_parquet(raw, columns=["aggregator", "faulty_nodes", "fraction", "availability"])
        for agg, g in df.groupby("aggregator", sort=False):
            a = g.groupby("faulty_nodes")[["fraction", "availability"]].mean()
            availability[agg] = {"fraction": a["fraction"].round(5).tolist(),
                                 "availability": a["availability"].round(5).tolist()}
    return {"name": cfg["name"], "title": cfg["sweep"].get("title", cfg["name"]),
            "fault": cfg["sweep"]["fault"], "by_source": cfg["sweep"].get("by_source", False),
            "nodes": cfg["nodes"], "seeds": summary["seeds"], "config_hash": summary["config_hash"],
            "threshold": summary["failure_prob_threshold"],
            "breaking_points": summary["breaking_points"], "curves": curves,
            "availability": availability}


def build_bundle(results_dir: str | Path = "results") -> dict:
    results = Path(results_dir)
    bundle = {"version": __version__, "causes": CAUSES, "insufficient": INSUFFICIENT,
              "sweeps": [], "calibration": None, "mango": None}
    for d in sorted(results.glob("bp_*")):
        if (d / "summary.json").exists():
            bundle["sweeps"].append(_sweep(d))

    cal = results / "calibration"
    if (cal / "summary.json").exists():
        c = json.loads((cal / "summary.json").read_text())
        cm = pd.read_csv(cal / "confusion_grouped_test.csv", index_col=0)
        c["confusion"] = {"rows": cm.index.tolist(), "cols": cm.columns.tolist(),
                          "counts": cm.to_numpy().tolist()}
        bundle["calibration"] = c

    m = results / "mango"
    if (m / "summary.json").exists():
        mango = json.loads((m / "summary.json").read_text())
        if (m / "curves.json").exists():
            mango["curves"] = json.loads((m / "curves.json").read_text())
        bundle["mango"] = mango
    return clean(bundle)
