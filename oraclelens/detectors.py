"""Node-level anomaly detectors. All are causal: round t uses only data up to t.

Each detector returns a boolean (R, N) array of flagged reports. Missing or late
reports are never flagged here; diagnosis handles them separately.
"""

from __future__ import annotations

import warnings

import numpy as np

from .simulator import SimResult


def _context(sim: SimResult):
    x = np.where(sim.valid, sim.obs, np.nan)
    has = (~np.isnan(x)).any(axis=1)
    med = np.full(sim.rounds, np.nan)
    med[has] = np.nanmedian(x[has], axis=1)
    return x, med


def robust_z(x: np.ndarray, med: np.ndarray, floor: float) -> np.ndarray:
    """Cross-sectional robust z-score of each report against the round median."""
    dev = np.abs(x - med[:, None])
    with np.errstate(all="ignore"):
        mad = np.nanmedian(dev, axis=1)
    scale = np.maximum(1.4826 * np.nan_to_num(mad), floor * np.abs(np.nan_to_num(med)))
    scale[scale == 0] = np.inf
    return dev / scale[:, None]


def mad(sim: SimResult, p: dict) -> np.ndarray:
    x, med = _context(sim)
    z = robust_z(x, med, p.get("floor", 0.0002))
    return np.nan_to_num(z) > p.get("k", 3.5)


def hampel(sim: SimResult, p: dict) -> np.ndarray:
    """Per-node Hampel filter on the residual vs consensus, using the node's own
    past window. Catches spikes; a sustained bias becomes its own baseline."""
    x, med = _context(sim)
    resid = x / med[:, None] - 1.0
    w, k, floor = int(p.get("window", 10)), p.get("k", 3.5), p.get("floor", 0.0002)
    flags = np.zeros_like(sim.valid)
    for t in range(w, sim.rounds):
        past = resid[t - w:t]
        with np.errstate(all="ignore"):
            centre = np.nanmedian(past, axis=0)
            spread = 1.4826 * np.nanmedian(np.abs(past - centre), axis=0)
        spread = np.maximum(np.nan_to_num(spread, nan=floor), floor)
        flags[t] = np.nan_to_num(np.abs(resid[t] - np.nan_to_num(centre)) / spread) > k
    return flags & sim.valid


def rolling(sim: SimResult, p: dict) -> np.ndarray:
    """Rolling-baseline detector: report vs the recent mean of the consensus.
    Fast and simple, but legitimate market moves trip it."""
    x, med = _context(sim)
    w, k, floor = int(p.get("window", 10)), p.get("k", 4.0), p.get("floor", 0.001)
    flags = np.zeros_like(sim.valid)
    for t in range(w, sim.rounds):
        past = med[t - w:t]
        base = np.nanmean(past)
        spread = max(np.nanstd(past), floor * abs(base))
        flags[t] = np.nan_to_num(np.abs(x[t] - base) / spread) > k
    return flags & sim.valid


def cusum(sim: SimResult, p: dict) -> np.ndarray:
    """Two-sided CUSUM on each node's signed robust z-score (deviation from the
    round median over that round's MAD). Accumulates small persistent bias that
    per-round thresholds miss; z is clipped so one spike cannot trigger alone."""
    x, med = _context(sim)
    dev = x - med[:, None]
    mad_t = 1.4826 * np.nan_to_num(np.nanmedian(np.abs(dev), axis=1))
    scale = np.maximum(mad_t, p.get("floor", 0.0002) * np.abs(np.nan_to_num(med)))
    scale[scale == 0] = np.inf
    zs = dev / scale[:, None]
    k, h, clip = p.get("k", 1.0), p.get("h", 10.0), p.get("clip", 5.0)
    pos = np.zeros(sim.n_nodes)
    neg = np.zeros(sim.n_nodes)
    flags = np.zeros_like(sim.valid)
    for t in range(sim.rounds):
        z = np.clip(zs[t], -clip, clip)
        ok = ~np.isnan(z)
        # Capped at 2h so an alarm clears within a few rounds once the fault ends.
        pos[ok] = np.clip(pos[ok] + z[ok] - k, 0.0, 2 * h)
        neg[ok] = np.clip(neg[ok] - z[ok] - k, 0.0, 2 * h)
        flags[t] = (pos > h) | (neg > h)
    return flags & sim.valid


def vol_mad(sim: SimResult, p: dict) -> np.ndarray:
    """MAD whose tolerance widens with recent realized volatility, since honest
    nodes disagree more when the market moves fast."""
    x, med = _context(sim)
    w, alpha = int(p.get("window", 20)), p.get("alpha", 0.5)
    rets = np.concatenate([[0.0], np.diff(np.log(med))])
    vol = np.array([np.nanstd(rets[max(0, t - w):t + 1]) if t > 1 else 0.0
                    for t in range(sim.rounds)])
    # include the current round's move: dispersion appears in the same round
    vol = np.maximum(vol, np.abs(np.nan_to_num(rets)))
    dev = np.abs(x - med[:, None])
    with np.errstate(all="ignore"):
        base = np.maximum(1.4826 * np.nan_to_num(np.nanmedian(dev, axis=1)),
                          p.get("floor", 0.0002) * np.abs(med))
    scale = np.sqrt(base ** 2 + (alpha * vol * np.abs(med)) ** 2)
    scale[scale == 0] = np.inf
    return np.nan_to_num(dev / scale[:, None]) > p.get("k", 3.5)


def _quiet(fn):
    def wrapped(sim, p):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            return fn(sim, p)
    wrapped.__name__, wrapped.__doc__ = fn.__name__, fn.__doc__
    return wrapped


DETECTORS = {name: _quiet(fn) for name, fn in
             {"mad": mad, "hampel": hampel, "rolling": rolling,
              "cusum": cusum, "vol_mad": vol_mad}.items()}


def run_detectors(sim: SimResult, cfg: dict) -> dict[str, np.ndarray]:
    params = cfg.get("detector_params", {})
    return {name: DETECTORS[name](sim, params.get(name, {})) for name in cfg["detectors"]}
