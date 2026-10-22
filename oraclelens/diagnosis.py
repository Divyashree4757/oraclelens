"""Incident building and rule-based cause attribution with confidence.

An incident is a run of abnormal rounds for one node (flagged by the chosen
detectors, missing, or late). Each incident gets a probability over eight
classes (no fault + seven causes). If the top probability is below
`abstain_below`, the prediction is `insufficient_evidence` instead of a guess.

Assumption: node-to-source assignments are known to the diagnoser. Real oracle
networks may not publish this, which would weaken the correlated-source rule.
"""

from __future__ import annotations

import numpy as np

from . import CAUSES, CAUSE_ID, INSUFFICIENT
from .simulator import SimResult


def _softmax(s: np.ndarray, temp: float) -> np.ndarray:
    e = np.exp(temp * (s - s.max()))
    return e / e.sum()


def abnormal_matrix(sim: SimResult, flags: dict, detectors: list[str]) -> np.ndarray:
    a = np.isnan(sim.obs) | sim.late
    for name in detectors:
        a = a | flags[name]
    return a


def find_incidents(abnormal: np.ndarray, merge_gap: int, start: int) -> list[tuple]:
    out = []
    R, N = abnormal.shape
    for node in range(N):
        rows = np.flatnonzero(abnormal[start:, node]) + start
        if rows.size == 0:
            continue
        s = prev = rows[0]
        for r in rows[1:]:
            if r - prev > merge_gap + 1:
                out.append((node, int(s), int(prev)))
                s = r
            prev = r
        out.append((node, int(s), int(prev)))
    return out


def _features(sim, node, s, e, abnormal, resid, z, consensus):
    T = slice(s, e + 1)
    n = e - s + 1
    raw = sim.obs[T, node]
    present = ~np.isnan(raw)
    on_time = present & ~sim.late[T, node]
    f = {"length": n, "flag_rounds": int(abnormal[T, node].sum())}
    f["density"] = f["flag_rounds"] / n
    f["missing_frac"] = float((~present).mean())
    f["late_frac"] = float((present & sim.late[T, node]).sum() / max(present.sum(), 1))

    dev = resid[T, node][on_time]
    f["mean_dev"] = float(np.mean(dev)) if dev.size else 0.0
    f["max_z"] = float(np.nanmax(z[T, node])) if on_time.any() else 0.0

    moves = np.abs(np.diff(np.log(consensus[max(s - 1, 0):e + 1])))
    f["market_move"] = float(np.nanmax(moves)) if moves.size else 0.0

    vals = raw[present]
    f["repeat_frac"] = float(np.mean(np.isclose(vals[1:], vals[:-1], rtol=1e-12, atol=0))) \
        if vals.size > 1 else 0.0

    # Replay / stale: does the report match the consensus from L rounds ago?
    lag_score = 0.0
    rows = np.arange(s, e + 1)[on_time]
    if rows.size and np.median(np.abs(dev)) > 0.002:
        e0 = np.median(np.abs(dev))
        vals_on = sim.obs[rows, node]
        best = min((np.median(np.abs(vals_on[rows - L >= 0] / consensus[rows[rows - L >= 0] - L] - 1))
                    for L in range(1, 41) if (rows - L >= 0).any()), default=e0)
        lag_score = float(np.clip(1.0 - best / e0, 0.0, 1.0))
    f["lag_score"] = lag_score

    # Trend: does |deviation| grow over the first 40 rounds of the incident?
    trend = 0.0
    a = np.abs(dev[:40])
    if a.size >= 8 and a.std() > 0:
        corr = float(np.corrcoef(np.arange(a.size), a)[0, 1])
        growth = a[-3:].mean() > 2 * a[:3].mean()
        trend = max(0.0, corr) * (1.0 if growth else 0.5)
    f["trend"] = trend

    # Peers: other nodes abnormal over most of this window, deviating alike.
    same, other = 0, 0
    if dev.size and abs(f["mean_dev"]) > 0:
        overlap = abnormal[T].mean(axis=0)
        for j in np.flatnonzero(overlap >= 0.5):
            if j == node:
                continue
            dj = resid[T, j]
            dj = dj[~np.isnan(dj)]
            if dj.size == 0:
                continue
            mj = dj.mean()
            if np.sign(mj) == np.sign(f["mean_dev"]) and abs(mj - f["mean_dev"]) < 0.5 * abs(f["mean_dev"]):
                if sim.source_of[j] == sim.source_of[node]:
                    same += 1
                else:
                    other += 1
    f["peers_same_source"], f["peers_other_source"] = same, other
    return f


def _scores(f: dict) -> np.ndarray:
    s = np.zeros(len(CAUSES))
    peers = f["peers_same_source"] + f["peers_other_source"]
    has_peers = min(1.0, peers / 2.0)
    same_frac = f["peers_same_source"] / peers if peers else 0.0
    stale = max(f["repeat_frac"], f["lag_score"]) * (1.0 - f["missing_frac"]) \
        * min(1.0, f["flag_rounds"] / 3.0)
    # A brief deviation during a big legitimate move is usually sampling lag.
    market = float(f["flag_rounds"] <= 2 and f["market_move"] > 0.01)
    trend = f["trend"] * min(1.0, f["length"] / 15.0)
    zfac = min(1.0, f["max_z"] / 10.0)
    short = 1.0 if (f["flag_rounds"] <= 3 or f["density"] < 0.6) else 0.4

    s[CAUSE_ID["offline"]] = f["missing_frac"]
    s[CAUSE_ID["delayed"]] = f["late_frac"]
    s[CAUSE_ID["stale"]] = stale
    s[CAUSE_ID["gradual_drift"]] = trend
    s[CAUSE_ID["correlated_source"]] = has_peers * same_frac * (1 - trend) * (1 - stale)
    s[CAUSE_ID["coordinated_manipulation"]] = has_peers * (1 - same_frac) * (1 - trend) * (1 - stale)
    s[CAUSE_ID["isolated_outlier"]] = (1 - has_peers) * zfac * short * (1 - trend) * (1 - stale) \
        * (1 - f["missing_frac"]) * (1 - f["late_frac"])
    s[CAUSE_ID["none"]] = 0.1 + max(0.8 * (f["flag_rounds"] <= 1) * (f["max_z"] < 6), 0.7 * market) \
        * (1 - f["missing_frac"]) * (1 - f["late_frac"])
    return s


def diagnose(sim: SimResult, flags: dict, cfg: dict) -> list[dict]:
    dcfg = cfg["diagnosis"]
    detectors = [d for d in dcfg["detectors"] if d in flags]
    abnormal = abnormal_matrix(sim, flags, detectors)
    x = np.where(sim.valid, sim.obs, np.nan)
    has = (~np.isnan(x)).any(axis=1)
    consensus = np.full(sim.rounds, np.nan)
    consensus[has] = np.nanmedian(x[has], axis=1)
    resid = x / consensus[:, None] - 1.0
    from .detectors import robust_z
    z = robust_z(x, consensus, cfg["detector_params"]["mad"].get("floor", 0.0002))

    incidents = []
    warmup = int(cfg["evaluation"]["warmup"])
    for node, s, e in find_incidents(abnormal, int(dcfg["merge_gap"]), warmup):
        f = _features(sim, node, s, e, abnormal, resid, z, consensus)
        probs = _softmax(_scores(f), float(dcfg["temperature"]))
        top = int(np.argmax(probs))
        lab = sim.labels[s:e + 1, node]
        nz = lab[lab != 0]
        truth = int(np.bincount(nz).argmax()) if nz.size else 0
        incidents.append({
            "node": node, "start": s, "end": e,
            "true_cause": CAUSES[truth],
            "predicted": CAUSES[top] if probs[top] >= dcfg["abstain_below"] else INSUFFICIENT,
            "top_cause": CAUSES[top],
            "confidence": float(probs[top]),
            "probs": [float(p) for p in probs],
            "features": f,
            "explanation": explain(f, CAUSES[top], float(probs[top]), dcfg["abstain_below"]),
        })
    return incidents


def explain(f: dict, cause: str, conf: float, abstain: float) -> str:
    parts = []
    if f["missing_frac"] > 0:
        parts.append(f"missing in {f['missing_frac']:.0%} of rounds")
    if f["late_frac"] > 0:
        parts.append(f"late in {f['late_frac']:.0%} of reports")
    if f["repeat_frac"] > 0.5:
        parts.append("value repeated while the market moved")
    if f["lag_score"] > 0.5:
        parts.append("values match the consensus from earlier rounds")
    if f["trend"] > 0.5:
        parts.append("deviation grows steadily")
    peers = f["peers_same_source"] + f["peers_other_source"]
    if peers:
        parts.append(f"{peers} other node(s) deviate the same way "
                     f"({f['peers_same_source']} share its source)")
    if f["market_move"] > 0.01 and f["flag_rounds"] <= 2:
        parts.append(f"consensus moved {f['market_move']:.1%} in one round")
    if f["max_z"] > 0:
        parts.append(f"peak robust z = {f['max_z']:.1f}")
    head = (f"Likely {cause.replace('_', ' ')} ({conf:.0%})" if conf >= abstain
            else f"Insufficient evidence (best guess {cause.replace('_', ' ')}, {conf:.0%})")
    caveats = []
    if peers >= 2:
        caveats.append("agreement among nodes does not show which side is correct")
    if cause == "none":
        caveats.append("a short deviation may still be an attack too small to classify")
    text = head + ": " + "; ".join(parts) + "."
    if caveats:
        text += " Cannot establish: " + "; ".join(caveats) + "."
    return text
