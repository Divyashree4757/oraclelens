"""OracleLens Lab: results explorer + live simulation API.

    python -m oraclelens.lab            # http://127.0.0.1:8000
    python -m oraclelens.lab --port 8080 --results results
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from ..config import resolve
from ..experiment import run_experiment
from ..simulator import FAULT_CAUSE
from .bundle import build_bundle, clean
from .page import render_page

LIMITS = {"rounds": (50, 2000), "nodes": (3, 61), "sources": (1, 20)}
ROOT = Path.cwd()


class SimRequest(BaseModel):
    config: Dict[str, Any] = {}
    seed: int = 0


def _round(a: np.ndarray, digits: int = 7) -> list:
    out = np.round(np.asarray(a, dtype=float), digits).astype(object)
    out[~np.isfinite(np.asarray(a, dtype=float))] = None
    return out.tolist()


def validate(cfg: dict) -> dict:
    cfg = resolve(cfg)
    for key, (lo, hi) in LIMITS.items():
        v = int(cfg[key])
        if not lo <= v <= hi:
            raise HTTPException(400, f"{key} must be between {lo} and {hi}, got {v}")
    for f in cfg["faults"]:
        if f.get("type") not in FAULT_CAUSE:
            raise HTTPException(400, f"Unknown fault type: {f.get('type')!r}. "
                                     f"Use one of: {', '.join(sorted(FAULT_CAUSE))}")
    if cfg["price"]["mode"] not in ("synthetic",):
        raise HTTPException(400, "The lab runs synthetic prices only; use the CLI for historical replay.")
    return cfg


def simulate_payload(cfg: dict, seed: int) -> dict:
    result, sim, aggs, flags, incidents = run_experiment(cfg, seed)
    names = list(flags)
    bits = np.zeros(sim.obs.shape, dtype=np.int64)
    for i, name in enumerate(names):
        bits |= flags[name].astype(np.int64) << i
    return clean({
        "config": cfg, "seed": seed, "provenance": result["provenance"],
        "rounds": sim.rounds, "nodes": sim.n_nodes, "warmup": cfg["evaluation"]["warmup"],
        "tolerance": cfg["evaluation"]["tolerance"],
        "truth": _round(sim.truth), "aggregates": {k: _round(v) for k, v in aggs.items()},
        "obs": _round(sim.obs), "late": sim.late.astype(int).tolist(),
        "labels": sim.labels.astype(int).tolist(), "source_of": sim.source_of.tolist(),
        "detectors": names, "flags": bits.tolist(),
        "events": sim.events, "metrics": result["metrics"],
        "incidents": [{k: v for k, v in i.items() if k != "features"} for i in incidents],
    })


def presets(experiments: Path) -> list:
    out = []
    for f in sorted(experiments.glob("*.yaml")):
        if f.name.startswith("bp_"):
            continue
        raw = yaml.safe_load(f.read_text()) or {}
        desc = ""
        for line in f.read_text().splitlines():
            if line.startswith("#"):
                desc = line.lstrip("# ").strip()
                break
        out.append({"name": raw.get("name", f.stem), "description": desc, "config": raw})
    return out


def create_app(results_dir: Path, experiments_dir: Path) -> FastAPI:
    app = FastAPI(title="OracleLens Lab", docs_url="/api/docs")

    @app.get("/", response_class=HTMLResponse)
    def index():
        return render_page(data=None, live=True)

    @app.get("/api/results")
    def results():
        return JSONResponse(build_bundle(results_dir))

    @app.get("/api/presets")
    def get_presets():
        return presets(experiments_dir)

    @app.get("/api/fault-types")
    def fault_types():
        return {k: v for k, v in FAULT_CAUSE.items()}

    @app.post("/api/simulate")
    def simulate(req: SimRequest):
        cfg = validate(req.config)
        return JSONResponse(simulate_payload(cfg, int(req.seed)))

    return app


def main(argv: Optional[list] = None) -> None:
    import uvicorn
    ap = argparse.ArgumentParser(description="Run the OracleLens Lab dashboard.")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--results", default="results")
    ap.add_argument("--experiments", default="experiments")
    args = ap.parse_args(argv)
    app = create_app(Path(args.results), Path(args.experiments))
    print(f"OracleLens Lab running at http://{args.host}:{args.port}  (Ctrl+C to stop)")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
