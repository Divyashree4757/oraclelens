"""CLI: python -m oraclelens.run --config experiments/slow_burn.yaml --seed 42"""

from __future__ import annotations

import argparse
import json

from .config import load_config
from .experiment import run_experiment


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Run one OracleLens experiment.")
    ap.add_argument("--config", required=True)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="runs")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    result, *_ = run_experiment(cfg, args.seed, out_dir=args.out)
    agg = result["metrics"]["aggregation"]
    tol = cfg["evaluation"]["tolerance"]
    print(f"run written to {result['run_dir']}")
    print(json.dumps({k: {"mean_error": v["mean_error"],
                          f"failure_rate@{tol:g}": v[f"failure_rate@{tol:g}"],
                          "availability": v["availability"]} for k, v in agg.items()}, indent=2))


if __name__ == "__main__":
    main()
