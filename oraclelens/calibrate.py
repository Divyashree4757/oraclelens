"""Does the diagnosis engine know when it is right?

    python -m oraclelens.calibrate --scenarios 200 --out results

Generates many random scenarios (1–3 faults drawn from a family library, plus
optional legitimate market shocks), diagnoses every incident, then splits by
*whole scenario* so similar incidents cannot leak between fitting and testing.

Two splits are evaluated:
  * grouped:  random 50/50 split of scenario instances
  * holdout:  scenarios containing the held-out families (replay, flash_spike)
              are test-only, so calibration must generalize to unseen attacks

An isotonic map from raw confidence to observed accuracy is fitted on the
training scenarios and evaluated on the test scenarios with ECE, Brier score,
coverage and a reliability diagram.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

from . import CAUSES, INSUFFICIENT
from .config import resolve
from .detectors import run_detectors
from .diagnosis import diagnose
from .metrics import brier_score, expected_calibration_error, reliability_table
from .plots import INK2, SERIES, figure, save, style
from .simulator import simulate

HOLDOUT_FAMILIES = ("replay", "flash_spike")


def draw_fault(family: str, rng: np.random.Generator, rounds: int, sources: int) -> dict:
    start = int(rng.integers(60, rounds - 80))
    end = int(min(rounds, start + rng.integers(30, 150)))
    sign = float(rng.choice([-1, 1]))
    if family == "outlier":
        return {"type": "outlier", "count": int(rng.integers(1, 4)), "prob": float(rng.uniform(0.05, 0.3)),
                "start": start, "end": end}
    if family == "collusion":
        return {"type": "collusion", "count": int(rng.integers(2, 7)),
                "bias": sign * float(rng.uniform(0.01, 0.08)), "start": start, "end": end}
    if family == "slow_burn":
        return {"type": "slow_burn", "count": int(rng.integers(1, 4)), "start": start,
                "growth": float(rng.uniform(2e-4, 2e-3)), "direction": sign}
    if family == "drift":
        return {"type": "drift", "count": int(rng.integers(1, 3)), "start": start,
                "rate": float(rng.uniform(1e-4, 1e-3)), "direction": sign}
    if family == "stale":
        return {"type": "stale", "count": int(rng.integers(1, 3)), "start": start, "end": end}
    if family == "replay":
        return {"type": "replay", "count": int(rng.integers(1, 3)), "start": start, "end": end,
                "age": int(rng.integers(5, 40))}
    if family == "delay":
        return {"type": "delay", "count": int(rng.integers(1, 5)), "start": start, "end": end,
                "extra_ms": float(rng.uniform(800, 3000))}
    if family == "offline":
        return {"type": "offline", "count": int(rng.integers(1, 7)), "start": start, "end": end}
    if family == "source_fault":
        return {"type": "source_fault", "source": int(rng.integers(0, sources)),
                "bias": sign * float(rng.uniform(0.01, 0.05)), "start": start,
                "end": int(min(rounds, start + rng.integers(5, 60)))}
    if family == "flash_spike":
        return {"type": "flash_spike", "source": int(rng.integers(0, sources)),
                "bias": sign * float(rng.uniform(0.05, 0.3)), "start": start}
    raise ValueError(family)


FAMILIES = ["outlier", "collusion", "slow_burn", "drift", "stale", "replay",
            "delay", "offline", "source_fault", "flash_spike"]


def generate(n_scenarios: int, rounds: int = 300, master_seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(master_seed)
    rows = []
    for sid in range(n_scenarios):
        fams = list(rng.choice(FAMILIES, size=int(rng.integers(1, 4)), replace=False))
        faults = [draw_fault(f, rng, rounds, 5) for f in fams]
        if rng.random() < 0.3:
            faults.insert(0, {"type": "market_shock", "start": int(rng.integers(60, rounds - 20)),
                              "size": float(rng.choice([-1, 1]) * rng.uniform(0.05, 0.2)),
                              "duration": int(rng.integers(1, 6))})
        cfg = resolve({"name": f"cal_{sid}", "rounds": rounds, "faults": faults})
        sim = simulate(cfg, seed=sid)
        for inc in diagnose(sim, run_detectors(sim, cfg), cfg):
            rows.append({"scenario": sid, "families": ",".join(sorted(fams)),
                         "true_cause": inc["true_cause"], "top_cause": inc["top_cause"],
                         "confidence": inc["confidence"], "probs": inc["probs"],
                         "length": inc["end"] - inc["start"] + 1})
    return pd.DataFrame(rows)


def _recalibrated_probs(probs: np.ndarray, new_top: np.ndarray) -> np.ndarray:
    """Replace the top probability, spread the rest in the original proportions."""
    out = probs.copy()
    top = probs.argmax(axis=1)
    rest = 1.0 - probs[np.arange(len(probs)), top]
    scale = np.where(rest > 0, (1.0 - new_top) / np.maximum(rest, 1e-12), 0.0)
    out *= scale[:, None]
    out[np.arange(len(probs)), top] = new_top
    return out


def evaluate(train: pd.DataFrame, test: pd.DataFrame, abstain: float) -> dict:
    iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
    iso.fit(train["confidence"], (train["top_cause"] == train["true_cause"]).astype(float))
    conf_raw = test["confidence"].to_numpy()
    correct = (test["top_cause"] == test["true_cause"]).to_numpy()
    conf_cal = iso.predict(conf_raw)
    probs = np.stack(test["probs"].to_numpy())
    true_idx = test["true_cause"].map(CAUSES.index).to_numpy()
    out = {"train_incidents": len(train), "test_incidents": len(test),
           "train_scenarios": int(train["scenario"].nunique()),
           "test_scenarios": int(test["scenario"].nunique()),
           "accuracy": float(correct.mean()),
           "per_class_recall": {c: float(correct[test["true_cause"].to_numpy() == c].mean())
                                for c in CAUSES if (test["true_cause"] == c).any()}}
    for tag, conf, p in (("raw", conf_raw, probs), ("calibrated", conf_cal, _recalibrated_probs(probs, conf_cal))):
        decided = conf >= abstain
        out[tag] = {"ece": expected_calibration_error(conf, correct),
                    "brier": brier_score(p, true_idx),
                    "coverage": float(decided.mean()),
                    "accuracy_when_decided": float(correct[decided].mean()) if decided.any() else None,
                    "reliability": reliability_table(conf, correct)}
    out["_conf"] = (conf_raw, conf_cal, correct)
    return out


def confusion(df: pd.DataFrame, abstain: float) -> pd.DataFrame:
    pred = np.where(df["confidence"] >= abstain, df["top_cause"], INSUFFICIENT)
    return pd.crosstab(df["true_cause"], pred).reindex(index=CAUSES, columns=CAUSES + [INSUFFICIENT],
                                                       fill_value=0)


def plot_reliability(results: dict, path):
    fig, axes = figure(9.5, 4.2, ncols=len(results))
    for ax, (name, r) in zip(axes[0], results.items()):
        ax.plot([0, 1], [0, 1], color=INK2, linestyle="--", linewidth=1, label="perfect calibration")
        for tag, color in (("raw", SERIES[1]), ("calibrated", SERIES[0])):
            rel = [b for b in r[tag]["reliability"] if b["count"] >= 5]
            ax.plot([b["mean_confidence"] for b in rel], [b["accuracy"] for b in rel], color=color,
                    linewidth=2, marker="o", markersize=5,
                    label=f"{tag} (ECE {r[tag]['ece']:.3f})")
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1.02)
        ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
        ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
        style(ax, f"{name} split", "Stated confidence", "Observed accuracy")
        ax.legend(frameon=False, fontsize=8, loc="upper left")
    save(fig, path)


def plot_confusion(cm: pd.DataFrame, path):
    import matplotlib.pyplot as plt
    norm = cm.div(cm.sum(axis=1).replace(0, 1), axis=0)
    fig, axes = figure(9.5, 5.6)
    ax = axes[0][0]
    ax.imshow(norm.to_numpy(), cmap=plt.get_cmap("Blues"), vmin=0, vmax=1, aspect="auto")
    ax.set_xticks(range(cm.shape[1]), [c.replace("_", " ") for c in cm.columns], rotation=35,
                  ha="right", fontsize=8)
    ax.set_yticks(range(cm.shape[0]), [c.replace("_", " ") for c in cm.index], fontsize=8)
    for i in range(cm.shape[0]):
        for j in range(cm.shape[1]):
            if cm.iat[i, j]:
                ax.text(j, i, str(cm.iat[i, j]), ha="center", va="center", fontsize=7,
                        color="white" if norm.iat[i, j] > 0.55 else "#0b0b0b")
    ax.set_title("Cause attribution on held-out scenarios (row-normalized shading, counts shown)",
                 loc="left", fontsize=11, fontweight="bold")
    ax.set_xlabel("Predicted", fontsize=9)
    ax.set_ylabel("True cause", fontsize=9)
    save(fig, path)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Held-out calibration of cause attribution.")
    ap.add_argument("--scenarios", type=int, default=200)
    ap.add_argument("--rounds", type=int, default=300)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="results")
    args = ap.parse_args(argv)

    out = Path(args.out) / "calibration"
    out.mkdir(parents=True, exist_ok=True)
    df = generate(args.scenarios, args.rounds, args.seed)
    df.drop(columns=["probs"]).to_parquet(out / "incidents.parquet", index=False)
    abstain = resolve({})["diagnosis"]["abstain_below"]

    rng = np.random.default_rng(args.seed)
    ids = df["scenario"].unique()
    test_ids = set(rng.choice(ids, size=len(ids) // 2, replace=False))
    is_test = df["scenario"].isin(test_ids)
    held = df["families"].apply(lambda s: any(f in s.split(",") for f in HOLDOUT_FAMILIES))
    splits = {"grouped": (df[~is_test], df[is_test]), "holdout-family": (df[~held], df[held])}

    results = {name: evaluate(tr, te, abstain) for name, (tr, te) in splits.items()}
    plot_reliability(results, out / "reliability.png")
    cm = confusion(splits["grouped"][1], abstain)
    cm.to_csv(out / "confusion_grouped_test.csv")
    plot_confusion(cm, out / "confusion.png")
    for r in results.values():
        r.pop("_conf")
    summary = {"scenarios": args.scenarios, "rounds": args.rounds, "seed": args.seed,
               "abstain_below": abstain, "holdout_families": HOLDOUT_FAMILIES, "splits": results}
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    for name, r in results.items():
        print(f"{name}: {r['test_incidents']} test incidents in {r['test_scenarios']} scenarios, "
              f"top-1 accuracy {r['accuracy']:.1%}")
        for tag in ("raw", "calibrated"):
            m = r[tag]
            print(f"  {tag:10s} ECE {m['ece']:.3f}  Brier {m['brier']:.3f}  coverage {m['coverage']:.1%}"
                  f"  accuracy when decided {m['accuracy_when_decided']:.1%}")


if __name__ == "__main__":
    main()
