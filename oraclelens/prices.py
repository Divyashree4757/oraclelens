"""True-price generation: synthetic jump-diffusion or replayed history with provenance."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .config import file_hash


def synthetic_log_returns(pcfg: dict, rounds: int, rng: np.random.Generator) -> np.ndarray:
    rets = rng.normal(pcfg["drift"], pcfg["vol"], rounds)
    jumps = rng.random(rounds) < pcfg["jump_rate"]
    rets[jumps] += rng.normal(0.0, pcfg["jump_scale"], int(jumps.sum()))
    rets[0] = 0.0
    return rets


def load_historical(pcfg: dict, rounds: int) -> tuple[np.ndarray, dict]:
    """Load a price column from CSV/Parquet. A sibling `<file>.manifest.json` is
    attached to provenance if present (source, range, frequency, gap policy)."""
    path = Path(pcfg["path"])
    df = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)
    series = df[pcfg["column"]].astype(float)
    n_missing = int(series.isna().sum())
    series = series.ffill().bfill()          # documented gap policy: forward-fill
    start = int(pcfg.get("offset", 0))
    values = series.to_numpy()[start:start + rounds]
    if len(values) < rounds:
        raise ValueError(f"{path} has {len(values)} usable rows, need {rounds}")
    provenance = {
        "path": str(path),
        "sha256": file_hash(path),
        "column": pcfg["column"],
        "offset": start,
        "rows_used": rounds,
        "missing_values_filled": n_missing,
        "gap_policy": "forward-fill, then back-fill leading gaps",
    }
    manifest = path.with_suffix(path.suffix + ".manifest.json")
    if manifest.exists():
        provenance["manifest"] = json.loads(manifest.read_text())
    return values, provenance


def apply_market_shocks(log_returns: np.ndarray, faults: list[dict]) -> np.ndarray:
    """Legitimate market moves (controls): spread a log move of `size` over `duration` rounds."""
    out = log_returns.copy()
    for f in faults:
        if f.get("type") != "market_shock":
            continue
        start, duration = int(f["start"]), int(f.get("duration", 5))
        move = np.log1p(float(f.get("size", -0.2)))
        out[start:start + duration] += move / duration
    return out


def true_prices(cfg: dict, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray, dict]:
    """Return (prices, per-round log returns, provenance)."""
    rounds, pcfg = cfg["rounds"], cfg["price"]
    if pcfg["mode"] == "series":          # explicit path, e.g. a case-study scenario
        base = np.asarray(pcfg["values"], dtype=float)[:rounds]
        rets = np.concatenate([[0.0], np.diff(np.log(base))])
        start = float(base[0])
        provenance = {"mode": "series", "sha256": hashlib.sha256(base.tobytes()).hexdigest()}
    elif pcfg["mode"] == "historical":
        base, provenance = load_historical(pcfg, rounds)
        rets = np.concatenate([[0.0], np.diff(np.log(base))])
        start = float(base[0])
    else:
        rets = synthetic_log_returns(pcfg, rounds, rng)
        start = float(pcfg["start"])
        provenance = {"mode": "synthetic", **{k: pcfg[k] for k in
                      ("start", "drift", "vol", "jump_rate", "jump_scale")}}
    rets = apply_market_shocks(rets, cfg["faults"])
    prices = start * np.exp(np.cumsum(rets))
    return prices, rets, provenance
