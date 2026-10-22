"""Experiment configuration: defaults, YAML loading and stable hashing."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import yaml

DEFAULT_CONFIG: dict = {
    "name": "unnamed",
    "rounds": 500,
    "nodes": 21,
    "sources": 5,
    "price": {
        "mode": "synthetic",       # synthetic | historical
        "start": 2000.0,
        "drift": 0.0,              # mean log-return per round
        "vol": 0.002,              # std of log-return per round
        "jump_rate": 0.01,         # probability of a jump per round
        "jump_scale": 0.03,        # std of jump size (log)
        "path": None,              # historical: CSV or Parquet file
        "column": "price",
        "offset": 0,               # historical: first row to use
    },
    "noise": {
        "node_sigma": 0.0005,      # per-node relative noise
        "source_sigma": 0.0005,    # per-exchange relative noise (shared)
        "timing_min": 0.85,        # nodes observe a fraction u~U(min,1) of the round's move
    },
    "network": {
        "latency_median_ms": 150.0,
        "latency_sigma": 0.6,      # lognormal shape
        "deadline_ms": 1000.0,     # reports after this are late and excluded
        "loss_prob": 0.0,
    },
    "faults": [],
    "detectors": ["mad", "hampel", "rolling", "cusum", "vol_mad"],
    "aggregators": ["median", "trimmed_mean", "weighted", "reputation", "quorum_median"],
    "detector_params": {
        "mad": {"k": 3.5, "floor": 0.0002},
        "hampel": {"window": 10, "k": 3.5, "floor": 0.0002},
        "rolling": {"window": 10, "k": 4.0, "floor": 0.001},
        "cusum": {"k": 1.0, "h": 10.0, "clip": 5.0, "floor": 0.0002},
        "vol_mad": {"k": 3.5, "floor": 0.0002, "window": 20, "alpha": 0.5},
    },
    "aggregator_params": {
        "trimmed_mean": {"trim": 0.2},
        "weighted": {"alpha": 0.05, "floor": 0.0002},
        "reputation": {"alpha": 0.005, "band": 0.005, "power": 2.0},
        "quorum_median": {"quorum": 0.67},
    },
    "evaluation": {
        "warmup": 50,
        "tolerance": 0.01,                 # failed round: relative error > tolerance
        "tolerances": [0.005, 0.01, 0.02],  # sensitivity analysis
        "failure_prob": 0.05,              # breaking point: P(failed round) > this
    },
    "diagnosis": {
        "detectors": ["mad", "cusum"],
        "merge_gap": 2,
        "abstain_below": 0.5,
        "temperature": 5.0,
    },
}


def deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def resolve(cfg: dict | None) -> dict:
    """Merge a partial config over the defaults."""
    return deep_merge(DEFAULT_CONFIG, cfg or {})


def load_config(path: str | Path) -> dict:
    with open(path) as fh:
        raw = yaml.safe_load(fh) or {}
    return resolve(raw)


def config_hash(cfg: dict) -> str:
    blob = json.dumps(cfg, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()


def file_hash(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
