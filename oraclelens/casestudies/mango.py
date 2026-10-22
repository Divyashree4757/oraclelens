"""Case study: a Mango Markets–style collateral pump (October 11, 2022).

    python -m oraclelens.casestudies.mango --out results

What is documented (see docs/case_study_mango.md for sources):
  * ~483M MNGO-PERP opened at ~3.8 cents; MNGO then traded roughly 10–30x its
    prior-day price for about 20 minutes, peaking near 91 cents.
  * About $116M was borrowed/withdrawn against the inflated unrealized profit.
  * Mango's team stated the oracle price reporting worked as designed: every
    source reported the (manipulated) market price faithfully.

Everything else here is a MODEL ASSUMPTION, listed in ASSUMPTIONS and written to
the output. This is a simplified mechanism model, not a replay of the incident.

The question: can defenses *outside* price consensus stop a price that every
oracle node reports honestly, and what do they cost legitimate borrowers?
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ..aggregators import median
from ..config import resolve
from ..detectors import mad
from ..plots import INK2, SERIES, figure, save, style
from ..simulator import simulate

DOCUMENTED = {
    "date": "2022-10-11",
    "perp_units": 483e6,
    "entry_price": 0.0382,
    "peak_price": 0.91,
    "pump_multiple_range": [10, 30],
    "reported_loss_usd": 116e6,
    "oracle_behaviour": "reported the manipulated market price as designed",
}

ASSUMPTIONS = {
    "round_length": "1 minute",
    "fair_price": DOCUMENTED["entry_price"],
    "attacker_deposit_usd": 10e6,
    "loan_to_value": 0.8,
    "pool_liquidity_usd": 116e6,  # chosen so the undefended model reproduces the reported loss
    "pump_start_round": 120,
    "pump_duration_rounds": 20,
    "borrow_cap_usd": 10e6,
    "twap_window": 60,
    "rate_limit_per_round": 0.02,
    "breaker_move": 0.15,          # 5-round move that trips the volatility breaker
    "breaker_sigma": 8.0,
    "breaker_pause_rounds": 60,
    "consensus_alarm_share": 0.3,
}


# ------------------------------------------------------------------ price paths
def attack_path(rng: np.random.Generator, rounds: int = 240) -> np.ndarray:
    fair, t0, dur = ASSUMPTIONS["fair_price"], ASSUMPTIONS["pump_start_round"], ASSUMPTIONS["pump_duration_rounds"]
    logp = np.log(fair) + np.cumsum(rng.normal(0, 0.003, rounds))
    logp -= logp[t0 - 1] - np.log(fair)
    lo, hi = DOCUMENTED["pump_multiple_range"]
    mult = np.ones(rounds)
    mult[t0:t0 + 3] = np.exp(np.linspace(np.log(3), np.log(12), 3))
    mult[t0 + 3:t0 + dur] = np.exp(rng.uniform(np.log(lo), np.log(hi), dur - 3))
    mult[t0 + 3 + int(rng.integers(0, dur - 3))] = DOCUMENTED["peak_price"] / fair
    mult[t0 + dur:t0 + dur + 10] = np.exp(np.linspace(np.log(mult[t0 + dur - 1]), np.log(0.8), 10))
    mult[t0 + dur + 10:] = 0.8
    return np.exp(logp) * mult


def control_paths(rng: np.random.Generator, rounds: int = 240) -> dict[str, np.ndarray]:
    base = 1.0 * np.exp(np.cumsum(rng.normal(0, 0.003, rounds)))
    rally, sharp = base.copy(), base.copy()
    rally[120:150] *= np.exp(np.linspace(0, np.log(1.4), 30))
    rally[150:] *= 1.4
    sharp[120:123] *= np.exp(np.linspace(0, np.log(1.25), 3))
    sharp[123:] *= 1.25
    return {"normal day": base, "legit rally +40% in 30 min": rally, "legit jump +25% in 3 min": sharp}


# ------------------------------------------------------------------- defenses
def oracle_feed(path: np.ndarray, seed: int):
    cfg = resolve({"name": "mango", "rounds": len(path), "price": {"mode": "series", "values": list(path)},
                   "evaluation": {"warmup": 0}})
    sim = simulate(cfg, seed)
    return sim, median(sim, {}), mad(sim, cfg["detector_params"]["mad"])


def valuation_and_pause(agg: np.ndarray, flags: np.ndarray, valid: np.ndarray) -> dict:
    a = ASSUMPTIONS
    R = len(agg)
    out = {}
    out["spot median (no defense)"] = (agg, np.zeros(R, bool))
    share = flags.sum(axis=1) / np.maximum(valid.sum(axis=1), 1)
    out["node-consensus alarm"] = (agg, share >= a["consensus_alarm_share"])
    w = a["twap_window"]
    twap = np.array([agg[max(0, t - w + 1):t + 1].mean() for t in range(R)])
    out[f"TWAP {w} min"] = (twap, np.zeros(R, bool))
    lim = np.empty(R)
    lim[0] = agg[0]
    for t in range(1, R):
        r = a["rate_limit_per_round"]
        lim[t] = np.clip(agg[t], lim[t - 1] * (1 - r), lim[t - 1] * (1 + r))
    out[f"rate limit {a['rate_limit_per_round']:.0%}/min"] = (lim, np.zeros(R, bool))
    logp = np.log(agg)
    pause = np.zeros(R, bool)
    until = -1
    for t in range(5, R):
        move = abs(logp[t] - logp[t - 5])
        # baseline volatility from the hour *before* the move being tested
        hist = np.diff(logp[max(0, t - 65):t - 5])
        sd = np.std(hist) if hist.size > 2 else 0.0
        if move > max(a["breaker_move"], a["breaker_sigma"] * sd * np.sqrt(5)):
            until = t + a["breaker_pause_rounds"]
        pause[t] = t <= until
    out["volatility circuit breaker"] = (agg, pause)
    out["TWAP + breaker"] = (twap, pause)
    out["per-account borrow cap"] = (agg, np.zeros(R, bool))
    return out


def run_borrower(price: np.ndarray, pause: np.ndarray, units: float, entry: float,
                 deposit: float, pool: float, cap: float | None) -> np.ndarray:
    """Borrower draws up to capacity = LTV * (deposit + unrealized PnL) whenever
    borrowing is not paused. Returns cumulative borrowing per round."""
    ltv = ASSUMPTIONS["loan_to_value"]
    limit = min(pool, cap) if cap else pool
    borrowed, out = 0.0, np.zeros(len(price))
    for t, p in enumerate(price):
        if not pause[t]:
            capacity = ltv * (deposit + units * (p - entry))
            borrowed = max(borrowed, min(limit, capacity))
        out[t] = borrowed
    return out


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Mango Markets-style case study.")
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--seeds", type=int, default=30)
    ap.add_argument("--out", default="results")
    args = ap.parse_args(argv)
    out = Path(args.out) / "mango"
    out.mkdir(parents=True, exist_ok=True)
    a, d = ASSUMPTIONS, DOCUMENTED

    t0 = a["pump_start_round"]
    fair_capacity = a["loan_to_value"] * a["attacker_deposit_usd"]

    def attack_once(seed):
        path = attack_path(np.random.default_rng(seed))
        sim, agg, flags = oracle_feed(path, seed)
        defenses = valuation_and_pause(agg, flags, sim.valid)
        rows, curves = [], {}
        for name, (price, pause) in defenses.items():
            cap = a["borrow_cap_usd"] if name == "per-account borrow cap" else None
            b = run_borrower(price, pause, d["perp_units"], d["entry_price"], a["attacker_deposit_usd"],
                             a["pool_liquidity_usd"], cap)
            curves[name] = b
            first_pause = np.flatnonzero(pause[t0:])
            rows.append({"seed": seed, "defense": name,
                         "attacker_borrowed_usd": float(b[-1]),
                         "excess_over_fair_capacity_usd": float(max(0.0, b[-1] - fair_capacity)),
                         "minutes_to_first_response": int(first_pause[0]) if first_pause.size else None})
        base = rows[0]["excess_over_fair_capacity_usd"]
        for r in rows:
            r["loss_prevented_vs_no_defense"] = 1 - r["excess_over_fair_capacity_usd"] / base if base else None
        share = float((flags[t0:t0 + a["pump_duration_rounds"]].sum(axis=1)
                       / sim.valid[t0:t0 + a["pump_duration_rounds"]].sum(axis=1)).max())
        return rows, curves, defenses, share

    rows, curves, defenses, flagged_share = attack_once(args.seed)
    all_rows, shares = [], []
    for s in range(args.seeds):     # robustness over random pump paths
        r, _, _, sh = attack_once(1000 + s)
        all_rows += r
        shares.append(sh)
    robust = (pd.DataFrame(all_rows).groupby("defense", sort=False)["loss_prevented_vs_no_defense"]
              .agg(["mean", "min", "max"]).reset_index())
    robust.to_csv(out / "attack_robustness.csv", index=False)

    # Legitimate-borrower controls: same defenses, honest price moves.
    controls = []
    for cname, cpath in control_paths(np.random.default_rng(args.seed + 1)).items():
        csim, cagg, cflags = oracle_feed(cpath, args.seed + 2)
        cdef = valuation_and_pause(cagg, cflags, csim.valid)
        ref = run_borrower(cdef["spot median (no defense)"][0], np.zeros(len(cagg), bool), 1e6, cagg[0],
                           2e5, 1e12, None)[-1]
        for name, (price, pause) in cdef.items():
            cap = a["borrow_cap_usd"] if name == "per-account borrow cap" else None
            b = run_borrower(price, pause, 1e6, cagg[0], 2e5, 1e12, cap)
            # capacity lost = shortfall vs no defense at the moment the move completes
            t_eval = 150 if "rally" in cname else 125
            spot_t = run_borrower(cdef["spot median (no defense)"][0], np.zeros(len(cagg), bool),
                                  1e6, cagg[0], 2e5, 1e12, None)[t_eval]
            controls.append({"control": cname, "defense": name,
                             "minutes_paused": int(pause.sum()),
                             "borrowing_capacity_vs_no_defense_at_move": float(b[t_eval] / spot_t) if spot_t else None,
                             "final_capacity_vs_no_defense": float(b[-1] / ref) if ref else None})

    results = pd.DataFrame(rows)
    ctrl = pd.DataFrame(controls)
    results.to_csv(out / "attack_results.csv", index=False)
    ctrl.to_csv(out / "control_results.csv", index=False)
    (out / "summary.json").write_text(json.dumps({
        "documented": d, "assumptions": a, "seed": args.seed,
        "max_share_of_nodes_flagged_during_pump": flagged_share,
        "max_share_flagged_across_seeds": float(max(shares)),
        "robustness_seeds": args.seeds,
        "loss_prevented_across_seeds": robust.to_dict(orient="records"),
        "attack": rows, "controls": controls}, indent=2))

    # Charts: price seen by each valuation rule, then cumulative attacker borrowing.
    fig, axes = figure(8, 4)
    ax = axes[0][0]
    for (name, (price, _)), color in zip(
            [(k, defenses[k]) for k in ("spot median (no defense)", f"TWAP {a['twap_window']} min",
                                        f"rate limit {a['rate_limit_per_round']:.0%}/min")], SERIES):
        ax.plot(np.arange(len(price)) - t0, price, color=color, linewidth=2, label=name)
    ax.set_yscale("log")
    ax.axvspan(0, a["pump_duration_rounds"], color=SERIES[7], alpha=0.08, linewidth=0)
    ax.text(a["pump_duration_rounds"] + 2, 0.045, "modeled pump window (shaded)", fontsize=8, color=INK2)
    style(ax, "Every node reports the pumped price; only the valuation rule differs",
          "Minutes from pump start", "MNGO price used for collateral ($, log)")
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    save(fig, out / "price.png")

    fig, axes = figure(8, 5.2)
    ax = axes[0][0]
    order = list(curves)
    for name, color in zip(order, SERIES):
        style_kw = {"linestyle": "--"} if name in ("node-consensus alarm", "volatility circuit breaker") else {}
        ax.plot(np.arange(len(curves[name])) - t0, curves[name] / 1e6, color=color, linewidth=2,
                label=name + (" (= no defense)" if name == "node-consensus alarm" else ""), **style_kw)
    ax.set_xlim(-10, 110)
    paused = np.flatnonzero(defenses["volatility circuit breaker"][1])
    reopen = (paused[-1] + 1 - t0) if paused.size else a["breaker_pause_rounds"]
    ax.axvline(reopen, color=INK2, linewidth=1, linestyle=":")
    ax.text(reopen + 1, 35, "breaker reopens;\nTWAP still remembers the pump", fontsize=8, color=INK2)
    style(ax, "Attacker borrowing under each defense (model)", "Minutes from pump start",
          "Cumulative borrowed ($M)")
    ax.legend(frameon=False, fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=3)
    save(fig, out / "borrowing.png")

    print(f"max share of nodes flagged by MAD during pump: {flagged_share:.0%}")
    print(results[["defense", "attacker_borrowed_usd", "loss_prevented_vs_no_defense",
                   "minutes_to_first_response"]].to_string(index=False))
    print(robust.to_string(index=False))
    print(f"max share of nodes flagged across {args.seeds} pump paths: {max(shares):.0%}")
    print(ctrl.to_string(index=False))


if __name__ == "__main__":
    main()
