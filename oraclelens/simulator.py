"""Deterministic oracle network simulator with a labelled fault and attack library.

Every injected fault writes a ground-truth cause label into `labels[round, node]`,
so detection, attribution and calibration can be scored exactly.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import CAUSE_ID
from .params import sample_params
from .prices import true_prices

# fault type -> ground-truth cause it produces
FAULT_CAUSE = {
    "outlier": "isolated_outlier",
    "collusion": "coordinated_manipulation",
    "slow_burn": "gradual_drift",
    "drift": "gradual_drift",
    "stale": "stale",
    "replay": "stale",
    "offline": "offline",
    "partition": "offline",
    "delay": "delayed",
    "source_fault": "correlated_source",
    "flash_spike": "correlated_source",
    "market_shock": "none",   # legitimate move: a control, never a fault
}


@dataclass
class SimResult:
    truth: np.ndarray            # (R,) true price at end of each round
    honest: np.ndarray           # (R, N) what each node would report if honest
    obs: np.ndarray              # (R, N) reported values, NaN = no report
    latency_ms: np.ndarray       # (R, N)
    late: np.ndarray             # (R, N) report arrived after the deadline
    labels: np.ndarray           # (R, N) ground-truth cause id, 0 = none
    source_of: np.ndarray        # (N,) exchange each node reads
    events: list = field(default_factory=list)
    provenance: dict = field(default_factory=dict)

    @property
    def rounds(self) -> int:
        return self.obs.shape[0]

    @property
    def n_nodes(self) -> int:
        return self.obs.shape[1]

    @property
    def valid(self) -> np.ndarray:
        """Reports usable for aggregation: present and on time."""
        return ~np.isnan(self.obs) & ~self.late


def _pick_nodes(f: dict, n: int, used: set, source_of: np.ndarray,
                rng: np.random.Generator) -> list[int]:
    if "source" in f:
        return [int(i) for i in np.flatnonzero(source_of == int(f["source"]))]
    if "nodes" in f:
        return [int(i) for i in f["nodes"]]
    k = int(f["count"]) if "count" in f else int(round(float(f.get("fraction", 0.0)) * n))
    k = max(0, min(k, n))
    free = [i for i in range(n) if i not in used]
    pool = free if len(free) >= k else list(range(n))
    return sorted(int(i) for i in rng.choice(pool, size=k, replace=False))


def simulate(cfg: dict, seed: int) -> SimResult:
    rng = np.random.default_rng(seed)
    # Draw any randomized fault parameters first, each from its own stream, so a
    # seed gives the same attack whatever else changes (e.g. how many attackers).
    cfg = {**cfg, "faults": [sample_params(f, np.random.default_rng([seed, i, 1]))
                             for i, f in enumerate(cfg["faults"])]}
    R, N, S = int(cfg["rounds"]), int(cfg["nodes"]), int(cfg["sources"])
    noise, net = cfg["noise"], cfg["network"]

    truth, rets, provenance = true_prices(cfg, rng)
    source_of = rng.permutation(np.arange(N) % S)

    # Honest observation: each node samples part-way through the round's move
    # (timing u), plus a shared per-exchange error and its own noise.
    u = rng.uniform(noise["timing_min"], 1.0, (R, N))
    lag = np.exp(-rets[:, None] * (1.0 - u))
    src_err = rng.normal(0.0, noise["source_sigma"], (R, S))[:, source_of]
    node_err = rng.normal(0.0, noise["node_sigma"], (R, N))
    honest = truth[:, None] * lag * (1.0 + src_err + node_err)

    obs = honest.copy()
    latency = rng.lognormal(np.log(net["latency_median_ms"]), net["latency_sigma"], (R, N))
    labels = np.zeros((R, N), dtype=np.int8)
    lost = rng.random((R, N)) < net["loss_prob"]
    obs[lost] = np.nan

    events, used = [], set()
    warmup = int(cfg["evaluation"]["warmup"])

    for idx, f in enumerate(cfg["faults"]):
        ftype = f["type"]
        if ftype not in FAULT_CAUSE:
            raise ValueError(f"unknown fault type: {ftype}")
        cause = CAUSE_ID[FAULT_CAUSE[ftype]]
        if ftype == "market_shock":
            events.append({"index": idx, "type": ftype, "nodes": [], "start": int(f["start"]),
                           "end": int(f["start"]) + int(f.get("duration", 5)), "cause": "none",
                           "params": {k: v for k, v in f.items() if k != "type"}})
            continue

        frng = np.random.default_rng([seed, idx])   # independent stream per fault
        nodes = _pick_nodes(f, N, used, source_of, rng)
        used.update(nodes)
        t0 = int(f.get("start", warmup))
        default_end = t0 + 1 if ftype == "flash_spike" else R
        t1 = min(int(f.get("end") or default_end), R)
        if not nodes or t0 >= t1:
            continue
        sl, cols, n_t = slice(t0, t1), np.array(nodes), t1 - t0
        steps = np.arange(1, n_t + 1)[:, None]

        if ftype == "outlier":
            hit = frng.random((n_t, len(nodes))) < float(f.get("prob", 0.2))
            lo, hi = f.get("size", [0.02, 0.2])
            mag = frng.uniform(lo, hi, hit.shape) * frng.choice([-1, 1], hit.shape)
            block = obs[sl][:, cols]
            block[hit] = honest[sl][:, cols][hit] * (1.0 + mag[hit])
            obs[sl, cols] = block
            lab = labels[sl][:, cols]
            lab[hit] = cause
            labels[sl, cols] = lab
        elif ftype == "collusion":
            bias = float(f.get("bias", 0.05)) * float(f.get("direction", 1.0))
            jitter = frng.normal(0.0, noise["node_sigma"] * 0.2, (n_t, len(nodes)))
            obs[sl, cols] = truth[sl, None] * (1.0 + bias + jitter)
            labels[sl, cols] = cause
        elif ftype == "slow_burn":
            # Before defection: unusually precise honest reports to build reputation.
            precision = float(f.get("trust_noise_factor", 0.2))
            pre = frng.normal(0.0, noise["node_sigma"] * precision, (t0, len(nodes)))
            obs[:t0, cols] = truth[:t0, None] * (1.0 + pre)
            growth = float(f.get("growth", 0.0005))
            cap = float(f.get("max_bias", 0.05))
            direction = float(f.get("direction", 1.0))
            bias = np.minimum(growth * steps, cap) * direction
            post = frng.normal(0.0, noise["node_sigma"] * precision, (n_t, len(nodes)))
            obs[sl, cols] = truth[sl, None] * (1.0 + bias + post)
            labels[sl, cols] = cause
        elif ftype == "drift":
            rate, cap = float(f.get("rate", 0.0005)), float(f.get("max_bias", 0.05))
            bias = np.minimum(rate * steps, cap) * float(f.get("direction", 1.0))
            obs[sl, cols] = honest[sl][:, cols] * (1.0 + bias)
            labels[sl, cols] = cause
        elif ftype == "stale":
            obs[sl, cols] = honest[max(t0 - 1, 0), cols][None, :]
            labels[sl, cols] = cause
        elif ftype == "replay":
            age = int(f.get("age", 20))
            src_rows = np.clip(np.arange(t0, t1) - age, 0, None)
            obs[sl, cols] = honest[src_rows][:, cols]
            labels[sl, cols] = cause
        elif ftype in ("offline", "partition"):
            obs[sl, cols] = np.nan
            labels[sl, cols] = cause
        elif ftype == "delay":
            extra = frng.exponential(float(f.get("extra_ms", 1500.0)), (n_t, len(nodes)))
            latency[sl, cols] += extra
        elif ftype in ("source_fault", "flash_spike"):
            bias = float(f.get("bias", 0.2 if ftype == "flash_spike" else 0.03)) \
                * float(f.get("direction", 1.0))
            obs[sl, cols] = honest[sl][:, cols] * (1.0 + bias)
            labels[sl, cols] = cause

        events.append({"index": idx, "type": ftype, "nodes": nodes, "start": t0,
                       "end": t1, "cause": FAULT_CAUSE[ftype],
                       "params": {k: v for k, v in f.items() if k != "type"}})

    late = (latency > net["deadline_ms"]) & ~np.isnan(obs)
    # Ground truth reflects what happened, injected or not: any late report is
    # a delayed observation and any lost report is an offline round.
    labels[late & (labels == 0)] = CAUSE_ID["delayed"]
    labels[lost & (labels == 0)] = CAUSE_ID["offline"]

    return SimResult(truth=truth, honest=honest, obs=obs, latency_ms=latency, late=late,
                     labels=labels, source_of=source_of, events=events,
                     provenance={"prices": provenance})
