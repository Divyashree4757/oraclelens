"""Randomized fault parameters.

Any fault parameter may be a distribution instead of a number:

    bias:      {uniform: [0.005, 0.08]}
    growth:    {loguniform: [0.0002, 0.002]}
    direction: {choice: [-1, 1]}
    start:     {uniform: [100, 250]}      # integer parameters are rounded

Values are drawn once per seed, so every run stays reproducible.
"""

from __future__ import annotations

import numpy as np

INT_PARAMS = {"start", "end", "count", "age", "duration", "source"}
KINDS = {"uniform", "loguniform", "choice", "normal"}


def is_distribution(v) -> bool:
    return isinstance(v, dict) and len(v) == 1 and next(iter(v)) in KINDS


def draw(spec: dict, rng: np.random.Generator):
    kind, arg = next(iter(spec.items()))
    if kind == "uniform":
        return float(rng.uniform(arg[0], arg[1]))
    if kind == "loguniform":
        return float(np.exp(rng.uniform(np.log(arg[0]), np.log(arg[1]))))
    if kind == "normal":
        return float(rng.normal(arg[0], arg[1]))
    choice = arg[int(rng.integers(len(arg)))]
    return choice.item() if hasattr(choice, "item") else choice


def sample_params(fault: dict, rng: np.random.Generator) -> dict:
    out = {}
    for key in sorted(fault):          # fixed order: draws do not depend on YAML order
        value = fault[key]
        if is_distribution(value):
            value = draw(value, rng)
            if key in INT_PARAMS:
                value = int(round(value))
        out[key] = value
    return out
