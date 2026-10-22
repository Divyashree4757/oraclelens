"""Run one experiment end to end and (optionally) write a self-contained run folder."""

from __future__ import annotations

import hashlib
import json
import platform
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from . import CAUSES, INSUFFICIENT, __version__
from .aggregators import run_aggregators
from .config import config_hash
from .detectors import run_detectors
from .diagnosis import diagnose
from .metrics import (aggregation_metrics, brier_score, detection_metrics,
                      expected_calibration_error, slow_burn_metrics)
from .simulator import simulate


def data_hash(sim) -> str:
    h = hashlib.sha256()
    for arr in (sim.truth, np.nan_to_num(sim.obs, nan=-1.0), sim.labels):
        h.update(np.ascontiguousarray(arr).tobytes())
    return h.hexdigest()


def attribution_summary(incidents: list[dict]) -> dict:
    if not incidents:
        return {"incidents": 0}
    conf = np.array([i["confidence"] for i in incidents])
    correct = np.array([i["top_cause"] == i["true_cause"] for i in incidents])
    decided = np.array([i["predicted"] != INSUFFICIENT for i in incidents])
    probs = np.array([i["probs"] for i in incidents])
    true_idx = np.array([CAUSES.index(i["true_cause"]) for i in incidents])
    return {
        "incidents": len(incidents),
        "top1_accuracy": float(correct.mean()),
        "coverage": float(decided.mean()),
        "accuracy_when_decided": float(correct[decided].mean()) if decided.any() else None,
        "ece": expected_calibration_error(conf, correct),
        "brier": brier_score(probs, true_idx),
        "confusion": {f"{t}->{p}": n for (t, p), n in
                      Counter((i["true_cause"], i["predicted"]) for i in incidents).most_common()},
    }


def run_experiment(cfg: dict, seed: int, out_dir: str | Path | None = None,
                   diagnose_incidents: bool = True) -> dict:
    sim = simulate(cfg, seed)
    aggs = run_aggregators(sim, cfg)
    flags = run_detectors(sim, cfg)
    ev = cfg["evaluation"]
    warmup, tol = int(ev["warmup"]), float(ev["tolerance"])

    metrics = {
        "aggregation": {k: aggregation_metrics(sim, v, warmup, ev["tolerances"]) for k, v in aggs.items()},
        "detection": {k: detection_metrics(sim, v, warmup) for k, v in flags.items()},
        "slow_burn": slow_burn_metrics(sim, aggs, flags, tol),
    }
    incidents = diagnose(sim, flags, cfg) if diagnose_incidents else []
    metrics["attribution"] = attribution_summary(incidents)

    provenance = {
        "oraclelens_version": __version__,
        "python": platform.python_version(),
        "numpy": np.__version__,
        "seed": seed,
        "config_hash": config_hash(cfg),
        "data_hash": data_hash(sim),
        "inputs": sim.provenance,
    }
    result = {"name": cfg["name"], "seed": seed, "provenance": provenance,
              "metrics": metrics, "events": sim.events}

    if out_dir is not None:
        run_dir = Path(out_dir) / cfg["name"] / f"seed{seed}_{provenance['config_hash'][:8]}"
        write_run(run_dir, cfg, sim, aggs, flags, incidents, result)
        result["run_dir"] = str(run_dir)
    return result, sim, aggs, flags, incidents


def write_run(run_dir: Path, cfg, sim, aggs, flags, incidents, result) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    R, N = sim.obs.shape
    rounds, nodes = np.repeat(np.arange(R), N), np.tile(np.arange(N), R)
    events = pd.DataFrame({
        "round": rounds, "node": nodes, "source": sim.source_of[nodes],
        "truth": np.repeat(sim.truth, N), "honest": sim.honest.ravel(),
        "reported": sim.obs.ravel(), "latency_ms": sim.latency_ms.ravel(),
        "late": sim.late.ravel(), "true_cause": np.array(CAUSES)[sim.labels.ravel()],
        **{f"flag_{k}": v.ravel() for k, v in flags.items()},
    })
    events.to_parquet(run_dir / "events.parquet", index=False)
    preds = pd.DataFrame({"round": np.arange(R), "truth": sim.truth,
                          **{f"agg_{k}": v for k, v in aggs.items()},
                          **{f"err_{k}": np.abs(v - sim.truth) / sim.truth for k, v in aggs.items()}})
    preds.to_parquet(run_dir / "predictions.parquet", index=False)
    inc = pd.DataFrame([{k: v for k, v in i.items() if k not in ("probs", "features")}
                        | {f"p_{c}": p for c, p in zip(CAUSES, i["probs"])}
                        | {f"f_{k}": v for k, v in i["features"].items()} for i in incidents])
    inc.to_parquet(run_dir / "incidents.parquet", index=False)
    (run_dir / "config.json").write_text(json.dumps(cfg, indent=2, sort_keys=True))
    (run_dir / "provenance.json").write_text(json.dumps(result["provenance"], indent=2))
    (run_dir / "metrics.json").write_text(json.dumps(result["metrics"], indent=2))
    (run_dir / "report.md").write_text(render_report(cfg, result, incidents))


def _fmt(v, pct=False):
    if v is None:
        return "–"
    return f"{v:.2%}" if pct else (f"{v:.3f}" if isinstance(v, float) else str(v))


def render_report(cfg, result, incidents) -> str:
    m, p = result["metrics"], result["provenance"]
    tol = cfg["evaluation"]["tolerance"]
    lines = [f"# OracleLens run: {cfg['name']} (seed {result['seed']})", "",
             f"Config hash `{p['config_hash'][:16]}` · data hash `{p['data_hash'][:16]}` · "
             f"OracleLens {p['oraclelens_version']}", "", "## Injected faults", ""]
    for ev in result["events"]:
        lines.append(f"- **{ev['type']}** ({ev['cause']}) on {len(ev['nodes'])} node(s), "
                     f"rounds {ev['start']}–{ev['end']}")
    if not result["events"]:
        lines.append("- none (control run)")
    lines += ["", "## Aggregation", "",
              f"| Method | Mean error | p95 error | Failed rounds (>{tol:.1%}) | Availability |",
              "| --- | --- | --- | --- | --- |"]
    for k, v in m["aggregation"].items():
        lines.append(f"| {k} | {_fmt(v['mean_error'], True)} | {_fmt(v['p95_error'], True)} | "
                     f"{_fmt(v[f'failure_rate@{tol:g}'], True)} | {_fmt(v['availability'], True)} |")
    lines += ["", "## Detection", "",
              "| Detector | Precision | Recall | False-positive rate | Median latency (rounds) |",
              "| --- | --- | --- | --- | --- |"]
    for k, v in m["detection"].items():
        lines.append(f"| {k} | {_fmt(v['precision'])} | {_fmt(v['recall'])} | "
                     f"{_fmt(v['false_positive_rate'], True)} | {_fmt(v['median_latency_rounds'])} |")
    a = m["attribution"]
    if a.get("incidents"):
        lines += ["", "## Diagnosis", "",
                  f"{a['incidents']} incidents · top-1 accuracy {a['top1_accuracy']:.1%} · "
                  f"coverage {a['coverage']:.1%} · ECE {a['ece']:.3f} · Brier {a['brier']:.3f}", "",
                  "Largest non-trivial incidents:", ""]
        notable = sorted((i for i in incidents if i["true_cause"] != "none" or i["predicted"] != "none"),
                         key=lambda i: -(i["end"] - i["start"]))[:8]
        for i in notable:
            lines.append(f"- Node {i['node']}, rounds {i['start']}–{i['end']} "
                         f"(truth: {i['true_cause']}). {i['explanation']}")
    if m["slow_burn"]:
        lines += ["", "## Slow-burn attack", "",
                  "| Aggregator | Rounds to success | Rounds to detection (MAD) | Damage before detection (MAD) |",
                  "| --- | --- | --- | --- |"]
        for r in m["slow_burn"]:
            lines.append(f"| {r['aggregator']} | {_fmt(r['rounds_to_success'])} | "
                         f"{_fmt(r.get('rounds_to_detection[mad]'))} | "
                         f"{_fmt(r.get('damage_before_detection[mad]'))} |")
    lines += ["", "_Thresholds here are OracleLens research benchmarks, not safety limits "
              "for any production oracle system._", ""]
    return "\n".join(lines)
