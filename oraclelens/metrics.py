"""Evaluation metrics: detection, aggregation, slow-burn damage, calibration, breaking point."""

from __future__ import annotations

import numpy as np

from . import CAUSE_ID, VALUE_FAULTS
from .simulator import SimResult


def _ratio(a: float, b: float):
    return float(a / b) if b else None


# ---------------------------------------------------------------- detection
def detection_metrics(sim: SimResult, flags: np.ndarray, warmup: int = 0) -> dict:
    valid = sim.valid.copy()
    valid[:warmup] = False
    pos = valid & np.isin(sim.labels, VALUE_FAULTS)
    neg = valid & (sim.labels == 0)
    tp, fp = int((flags & pos).sum()), int((flags & neg).sum())
    fn = int((~flags & pos).sum())
    latencies, missed = [], 0
    for ev in sim.events:
        if CAUSE_ID.get(ev["cause"], 0) not in VALUE_FAULTS:
            continue
        for node in ev["nodes"]:
            rows = np.flatnonzero(sim.labels[ev["start"]:ev["end"], node] != 0)
            if rows.size == 0:
                continue
            first = ev["start"] + rows[0]
            hits = np.flatnonzero(flags[first:ev["end"], node])
            if hits.size:
                latencies.append(int(hits[0]))
            else:
                missed += 1
    n_faults = len(latencies) + missed
    return {
        "precision": _ratio(tp, tp + fp),
        "recall": _ratio(tp, tp + fn),
        "false_positive_rate": _ratio(fp, int(neg.sum())),
        "true_positives": tp, "false_positives": fp, "false_negatives": fn,
        "faults_detected": _ratio(len(latencies), n_faults),
        "median_latency_rounds": float(np.median(latencies)) if latencies else None,
        "mean_latency_rounds": float(np.mean(latencies)) if latencies else None,
    }


# --------------------------------------------------------------- aggregation
def relative_error(agg: np.ndarray, truth: np.ndarray) -> np.ndarray:
    return np.abs(agg - truth) / np.abs(truth)


def aggregation_metrics(sim: SimResult, agg: np.ndarray, warmup: int,
                        tolerances: list[float]) -> dict:
    err = relative_error(agg, sim.truth)[warmup:]
    answered = ~np.isnan(err)
    e = err[answered]
    out = {
        "availability": float(answered.mean()) if err.size else None,
        "mean_error": float(e.mean()) if e.size else None,
        "median_error": float(np.median(e)) if e.size else None,
        "p95_error": float(np.quantile(e, 0.95)) if e.size else None,
        "max_error": float(e.max()) if e.size else None,
    }
    for tol in tolerances:
        out[f"failure_rate@{tol:g}"] = float((e > tol).mean()) if e.size else None
    return out


# ------------------------------------------------------------------ slow burn
def slow_burn_metrics(sim: SimResult, aggs: dict, flags: dict, tolerance: float) -> list[dict]:
    """For each slow-burn attack: honest rounds spent building trust, rounds from
    first malicious deviation to success (error > tolerance) and to detection,
    and cumulative error before detection. 'Never' is recorded as None."""
    results = []
    for ev in sim.events:
        if ev["type"] != "slow_burn":
            continue
        t0, t1, nodes = ev["start"], ev["end"], ev["nodes"]
        for agg_name, agg in aggs.items():
            err = np.nan_to_num(relative_error(agg, sim.truth), nan=0.0)
            succ = np.flatnonzero(err[t0:t1] > tolerance)
            row = {"aggregator": agg_name, "attackers": len(nodes), "trust_rounds": t0,
                   "rounds_to_success": int(succ[0]) if succ.size else None}
            for det_name, f in flags.items():
                det = np.flatnonzero(f[t0:t1][:, nodes].any(axis=1))
                end = t0 + det[0] if det.size else t1
                row[f"rounds_to_detection[{det_name}]"] = int(det[0]) if det.size else None
                row[f"damage_before_detection[{det_name}]"] = float(err[t0:end].sum())
            results.append(row)
    return results


# ----------------------------------------------------------------- calibration
def expected_calibration_error(conf: np.ndarray, correct: np.ndarray, bins: int = 10) -> float:
    conf, correct = np.asarray(conf, float), np.asarray(correct, float)
    if conf.size == 0:
        return float("nan")
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(conf, edges[1:-1]), 0, bins - 1)
    ece = 0.0
    for b in range(bins):
        m = idx == b
        if m.any():
            ece += m.mean() * abs(conf[m].mean() - correct[m].mean())
    return float(ece)


def reliability_table(conf, correct, bins: int = 10) -> list[dict]:
    conf, correct = np.asarray(conf, float), np.asarray(correct, float)
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(conf, edges[1:-1]), 0, bins - 1)
    return [{"bin_low": float(edges[b]), "bin_high": float(edges[b + 1]),
             "count": int((idx == b).sum()),
             "mean_confidence": float(conf[idx == b].mean()) if (idx == b).any() else None,
             "accuracy": float(correct[idx == b].mean()) if (idx == b).any() else None}
            for b in range(bins)]


def brier_score(probs: np.ndarray, true_idx: np.ndarray) -> float:
    probs = np.asarray(probs, float)
    if probs.size == 0:
        return float("nan")
    onehot = np.zeros_like(probs)
    onehot[np.arange(len(true_idx)), np.asarray(true_idx)] = 1.0
    return float(np.mean(np.sum((probs - onehot) ** 2, axis=1)))


# --------------------------------------------------------------- breaking point
def breaking_point(fractions, failure_probs, threshold: float):
    """Smallest faulty fraction f with P(failed round) > threshold, else None."""
    for f, p in sorted(zip(fractions, failure_probs)):
        if p is not None and p > threshold:
            return float(f)
    return None
