"""Breaking-point sweeps.

    python -m oraclelens.sweep --config experiments/bp_collusion.yaml --out results

For each number of faulty nodes k = 0..max (fraction f = k/N) and each seed, the
fault template is injected into k nodes and every aggregator is scored. The
failure probability at f is the share of evaluated rounds with relative error
above the tolerance, averaged over seeds. The breaking point is

    f* = min { f : P(E_t > tolerance) > failure_prob }

with a 95% bootstrap interval over seeds. It is a research benchmark, not a
safety threshold for any production oracle.
"""

from __future__ import annotations

import argparse
import copy
import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from . import CAUSE_ID
from .aggregators import run_aggregators
from .config import config_hash, load_config
from .metrics import breaking_point, relative_error
from .plots import ENTITY_COLOR, INK2, figure, save, style
from .simulator import simulate


def run_sweep(cfg: dict, seeds: int | None = None) -> pd.DataFrame:
    sw = cfg["sweep"]
    n = int(cfg["nodes"])
    by_source = bool(sw.get("by_source", False))
    default = range(0, int(cfg["sources"]) + 1) if by_source else range(0, int(round(0.6 * n)) + 1)
    counts = sw.get("counts") or list(default)
    n_seeds = int(seeds or sw.get("seeds", 30))
    warmup = int(cfg["evaluation"]["warmup"])
    tols = cfg["evaluation"]["tolerances"]
    rows = []
    for k in counts:
        for seed in range(n_seeds):
            c = copy.deepcopy(cfg)
            if by_source:   # k whole exchanges fail: every node reading them is affected
                new = [dict(sw["fault"], source=s) for s in range(k)]
            else:
                new = [dict(sw["fault"], count=int(k))] if k > 0 else []
            c["faults"] = list(cfg["faults"]) + new
            sim = simulate(c, seed)
            # share of nodes reading a failed exchange (only the injected cause counts)
            frac = (float((sim.labels[warmup:] == CAUSE_ID["correlated_source"]).any(axis=0).mean())
                    if by_source else k / n)
            drawn = json.dumps([e.get("params", {}) for e in sim.events], default=float)
            for name, agg in run_aggregators(sim, c).items():
                err = relative_error(agg, sim.truth)[warmup:]
                ok = ~np.isnan(err)
                row = {"faulty_nodes": k, "fraction": frac, "seed": seed, "aggregator": name,
                       "fault_params": drawn,
                       "availability": float(ok.mean()),
                       "mean_error": float(err[ok].mean()) if ok.any() else np.nan}
                for t in tols:
                    # unavailable rounds are not failures; availability is reported separately
                    row[f"fail@{t:g}"] = float((err[ok] > t).mean()) if ok.any() else np.nan
                rows.append(row)
    return pd.DataFrame(rows)


def summarize(df: pd.DataFrame, tol: float, threshold: float, n_boot: int = 1000,
              rng_seed: int = 0) -> tuple[pd.DataFrame, dict]:
    col = f"fail@{tol:g}"
    rng = np.random.default_rng(rng_seed)
    curves, bps = [], {}
    for name, g in df.groupby("aggregator", sort=False):
        # pivot on the attacker count; x position = mean affected fraction for that count
        piv = g.pivot(index="seed", columns="faulty_nodes", values=col).sort_index(axis=1)
        fr = g.groupby("faulty_nodes")["fraction"].mean().reindex(piv.columns).to_numpy()
        mat = piv.to_numpy()
        boot_idx = rng.integers(0, mat.shape[0], (n_boot, mat.shape[0]))
        boot_means = np.nanmean(mat[boot_idx], axis=1)          # (n_boot, n_fr)
        lo, hi = np.nanpercentile(boot_means, [2.5, 97.5], axis=0)
        mean = np.nanmean(mat, axis=0)
        avail = g.groupby("faulty_nodes")["availability"].mean().reindex(piv.columns).to_numpy()
        for i, f in enumerate(fr):
            curves.append({"aggregator": name, "fraction": f, "fail_prob": mean[i],
                           "ci_low": lo[i], "ci_high": hi[i], "availability": avail[i]})
        point = breaking_point(fr, mean, threshold)
        boots = [breaking_point(fr, b, threshold) for b in boot_means]
        unbroken = sum(b is None for b in boots) / n_boot
        finite = [b for b in boots if b is not None]
        bps[name] = {
            "breaking_point": point,
            "ci_low": float(np.percentile(finite, 2.5)) if finite else None,
            "ci_high": float(np.percentile(finite, 97.5)) if finite else None,
            "share_of_resamples_never_breaking": unbroken,
        }
    return pd.DataFrame(curves), bps


def plot_curves(curves: pd.DataFrame, bps: dict, title: str, tol: float, threshold: float, path):
    fig, axes = figure()
    ax = axes[0][0]
    seen, labelled = {}, set()
    for name, g in curves.groupby("aggregator", sort=False):
        color = ENTITY_COLOR.get(name, "#2a78d6")
        label = name.replace("_", " ")
        key = tuple(np.round(g["fail_prob"].to_numpy(), 6))
        if key in seen:   # identical curve would be hidden: say so in the legend
            label += f" (= {seen[key]})"
        else:
            seen[key] = name.replace("_", " ")
        ax.fill_between(g["fraction"], g["ci_low"], g["ci_high"], color=color, alpha=0.15, linewidth=0)
        ax.plot(g["fraction"], g["fail_prob"], color=color, linewidth=2, marker="o", markersize=4,
                label=label)
        bp = bps[name]["breaking_point"]
        if bp is not None and not label.endswith(")") and round(bp, 6) not in labelled:
            labelled.add(round(bp, 6))
            y = float(g.loc[g["fraction"] == bp, "fail_prob"].iloc[0])
            ax.annotate(f"{bp:.0%}", (bp, y), textcoords="offset points", xytext=(4, 6),
                        fontsize=8, color=INK2)
    ax.axhline(threshold, color=INK2, linestyle="--", linewidth=1)
    ax.text(0.0, threshold, f" failure threshold {threshold:.0%}", va="bottom", fontsize=8, color=INK2)
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    ax.set_ylim(-0.02, 1.02)
    style(ax, title, "Faulty nodes", f"P(round error > {tol:.1%})")
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    save(fig, path)


def plot_availability(df: pd.DataFrame, title: str, path):
    fig, axes = figure(7.5, 3.4)
    ax = axes[0][0]
    for name, g in df.groupby("aggregator", sort=False):
        a = g.groupby("faulty_nodes")[["fraction", "availability"]].mean()
        ax.plot(a["fraction"], a["availability"], color=ENTITY_COLOR.get(name, "#2a78d6"), linewidth=2,
                marker="o", markersize=4, label=name.replace("_", " "))
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    ax.set_ylim(-0.02, 1.05)
    style(ax, f"{title}: availability", "Faulty nodes", "Rounds with an answer")
    ax.legend(frameon=False, fontsize=8, loc="lower left")
    save(fig, path)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Run a breaking-point sweep.")
    ap.add_argument("--config", required=True)
    ap.add_argument("--out", default="results")
    ap.add_argument("--seeds", type=int, default=None)
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    out = Path(args.out) / cfg["name"]
    out.mkdir(parents=True, exist_ok=True)
    df = run_sweep(cfg, args.seeds)
    df.to_parquet(out / "sweep_raw.parquet", index=False)

    ev = cfg["evaluation"]
    summary = {"name": cfg["name"], "config_hash": config_hash(cfg),
               "seeds": int(df["seed"].nunique()), "fault": cfg["sweep"]["fault"],
               "failure_prob_threshold": ev["failure_prob"], "breaking_points": {}}
    for tol in ev["tolerances"]:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            curves, bps = summarize(df, tol, ev["failure_prob"])
        curves.to_csv(out / f"curves_tol{tol:g}.csv", index=False)
        summary["breaking_points"][f"{tol:g}"] = bps
        plot_curves(curves, bps, cfg["sweep"].get("title", cfg["name"]), tol, ev["failure_prob"],
                    out / f"breaking_point_tol{tol:g}.png")
    plot_availability(df, cfg["sweep"].get("title", cfg["name"]), out / "availability.png")
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    (out / "config.json").write_text(json.dumps(cfg, indent=2, sort_keys=True))
    main_tol = f"{ev['tolerance']:g}"
    print(f"{cfg['name']}: breaking points at tolerance {main_tol}")
    for name, b in summary["breaking_points"][main_tol].items():
        bp = "never (within sweep)" if b["breaking_point"] is None else f"{b['breaking_point']:.1%}"
        print(f"  {name:14s} {bp}  CI [{b['ci_low']}, {b['ci_high']}]")


if __name__ == "__main__":
    main()
