#!/usr/bin/env bash
# Regenerates every result in results/ and the example runs in runs/ from configs + seeds.
set -euo pipefail
python -m pytest -q
for c in independent collusion slow_burn reputation_exploit source partition; do
  python -m oraclelens.sweep --config "experiments/bp_${c}.yaml" --out results
done
python -m oraclelens.calibrate --scenarios 200 --out results
python -m oraclelens.casestudies.mango --out results
python -m oraclelens.run --config experiments/slow_burn.yaml --seed 42
python -m oraclelens.run --config experiments/mixed_faults.yaml --seed 42
