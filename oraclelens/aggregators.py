"""Aggregation strategies: combine valid node reports into one answer per round."""

from __future__ import annotations

import math

import numpy as np

from .simulator import SimResult


def _masked(sim: SimResult) -> np.ndarray:
    return np.where(sim.valid, sim.obs, np.nan)


def median(sim: SimResult, params: dict) -> np.ndarray:
    x = _masked(sim)
    out = np.full(sim.rounds, np.nan)
    has = (~np.isnan(x)).any(axis=1)
    out[has] = np.nanmedian(x[has], axis=1)
    return out


def trimmed_mean(sim: SimResult, params: dict) -> np.ndarray:
    trim = float(params.get("trim", 0.2))
    x = _masked(sim)
    out = np.full(sim.rounds, np.nan)
    for t in range(sim.rounds):
        v = np.sort(x[t][~np.isnan(x[t])])
        if v.size == 0:
            continue
        k = int(math.floor(trim * v.size))
        core = v[k:v.size - k] if v.size - 2 * k > 0 else v
        out[t] = core.mean()
    return out


def weighted(sim: SimResult, params: dict) -> np.ndarray:
    """Reliability-weighted mean. Reputation = EWMA of each node's relative
    distance from the round median; weight = 1 / (reputation error + floor)."""
    alpha, floor = float(params.get("alpha", 0.05)), float(params.get("floor", 0.0002))
    x = _masked(sim)
    err = np.full(sim.n_nodes, 0.001)   # neutral prior reputation
    out = np.full(sim.rounds, np.nan)
    for t in range(sim.rounds):
        ok = ~np.isnan(x[t])
        if not ok.any():
            continue
        w = 1.0 / (err[ok] + floor)
        out[t] = float(np.sum(w * x[t][ok]) / np.sum(w))
        med = np.median(x[t][ok])
        err[ok] = (1 - alpha) * err[ok] + alpha * np.abs(x[t][ok] / med - 1.0)
    return out


def reputation(sim: SimResult, params: dict) -> np.ndarray:
    """Reputation-weighted mean with long memory. A node's reputation is the
    EWMA share of rounds it reported within `band` of the round median;
    weight = reputation ** power. Trust is earned and lost slowly."""
    alpha = float(params.get("alpha", 0.005))
    band, power = float(params.get("band", 0.005)), float(params.get("power", 2.0))
    x = _masked(sim)
    rep = np.ones(sim.n_nodes)
    out = np.full(sim.rounds, np.nan)
    for t in range(sim.rounds):
        ok = ~np.isnan(x[t])
        if not ok.any():
            continue
        w = rep[ok] ** power + 1e-9
        out[t] = float(np.sum(w * x[t][ok]) / np.sum(w))
        med = np.median(x[t][ok])
        good = (np.abs(x[t][ok] / med - 1.0) < band).astype(float)
        rep[ok] = (1 - alpha) * rep[ok] + alpha * good
    return out


def quorum_median(sim: SimResult, params: dict) -> np.ndarray:
    """Median that refuses to answer without a quorum of fresh reports."""
    need = math.ceil(float(params.get("quorum", 0.67)) * sim.n_nodes)
    out = median(sim, params)
    out[sim.valid.sum(axis=1) < need] = np.nan
    return out


AGGREGATORS = {
    "median": median,
    "trimmed_mean": trimmed_mean,
    "weighted": weighted,
    "reputation": reputation,
    "quorum_median": quorum_median,
}


def run_aggregators(sim: SimResult, cfg: dict) -> dict[str, np.ndarray]:
    params = cfg.get("aggregator_params", {})
    return {name: AGGREGATORS[name](sim, params.get(name, {})) for name in cfg["aggregators"]}
