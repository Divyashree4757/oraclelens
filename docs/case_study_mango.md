# Case study: Mango Markets collateral pump (October 11, 2022)

Run: `python -m oraclelens.casestudies.mango --out results` (outputs in `results/mango/`).

## 1. Documented facts

These come from public sources, paraphrased; nothing else in this study is a historical claim.

- The exploit took place on October 11, 2022 (about 23:19 UTC) with a total loss of roughly $116M. [CertiK alert, via ForkLog]
- A wallet opened a short of about 483M MNGO perpetual futures at about 3.8 cents, matched by a long on a linked wallet. Roughly $4M of spot MNGO was bought across three venues, and MNGO traded at about 10–30x its prior-day price for roughly 20 minutes, peaking near 91 cents. The long's unrealized profit was used as collateral to withdraw about $116M. [Solidus Labs order-book analysis]
- Mango's team stated that the oracle providers were not at fault and that price reporting worked as it should have; some analysts described the event as a pump on thinly traded books rather than an oracle failure. [ForkLog, quoting Mango and commentators]

**What this means for OracleLens:** the oracle nodes were not wrong. Every source reported a genuine but manipulated market price. Defenses that rely on nodes disagreeing cannot see this. This study therefore tests defenses *outside* price consensus.

## 2. Model assumptions

All values are in `ASSUMPTIONS` in `oraclelens/casestudies/mango.py` and are written to `results/mango/summary.json`.

| Assumption | Value | Note |
| --- | --- | --- |
| Round length | 1 minute | |
| Fair price | $0.0382 | the documented entry price |
| Pump shape | 3-minute ramp, ~20 minutes at 10–30x, collapse | follows the documented range, not the exact tick path |
| Attacker deposit | $10M | assumption |
| Loan-to-value | 80% | assumption |
| Pool liquidity | $116M | set so the undefended model reproduces the reported loss |
| Oracle network | 21 honest nodes reading the manipulated market | matches the documented oracle behaviour |

This is a simplified mechanism model. It is not a replay of Mango's on-chain execution, margin engine or order books.

## 3. Defenses tested

| Defense | Rule |
| --- | --- |
| Spot median | Collateral valued at the oracle median (baseline) |
| Node-consensus alarm | Pause borrowing if ≥30% of nodes are flagged by MAD |
| TWAP 60 min | Value collateral at the 60-minute average |
| Rate limit | Accepted price may move at most 2% per minute |
| Volatility circuit breaker | Pause new borrowing for 60 minutes if a 5-minute move exceeds max(15%, 8σ of the previous hour) |
| TWAP + breaker | Both |
| Borrow cap | $10M per account |

Each defense is also run on three **legitimate** price paths (normal day, +40% rally over 30 minutes, +25% jump in 3 minutes) with an honest leveraged borrower, to measure what it costs real users.

## 4. Results

Loss prevented = reduction in borrowing above what the account could borrow at the fair price, versus no defense. Range is over 30 random pump paths.

| Defense | Loss prevented (mean, min–max) | Cost to legitimate borrowers |
| --- | --- | --- |
| Node-consensus alarm | 0% (never fired; at most 19% of nodes flagged) | none |
| TWAP 60 min | 18% (6–28%) | ~50% less borrowing capacity at the moment of a legitimate move; ~7% less on a normal day |
| Rate limit 2%/min | 90% (90–90%) | 31% less capacity right after the +25% jump; recovers within minutes |
| Volatility circuit breaker | 99.6% (98.8–100%) | borrowing paused 64 minutes after the legitimate +25% jump |
| TWAP + breaker | 39% (29–51%) | combines both costs |
| Borrow cap $10M | 98% | none in these controls (honest positions were small) |

## 5. Findings

1. **Consensus-based detection gives no signal.** All nodes agreed on the pumped price. This is the "agreement does not prove correctness" limitation, shown on a real incident pattern.
2. **Averaging alone is weak.** A 60-minute TWAP slowed borrowing but still let most of the loss through, because the pump lasted a third of the window at 10–30x.
3. **Combining defenses can make things worse.** TWAP + breaker prevented less than the breaker alone: when the pause ended, the TWAP still contained the pumped prices, and borrowing resumed against them. Defenses must be evaluated together, not assumed additive.
4. **The strongest defenses have real costs.** The breaker stopped nearly all modeled loss but would have frozen honest borrowing for an hour after a legitimate sharp move. A borrow cap was cheap here only because honest positions were small.

## 6. Limitations

- Pool liquidity is calibrated to the reported loss, so the baseline matches by construction.
- One attacker account, no liquidations, no order-book or liquidity model, no governance actions.
- Thresholds were chosen once, not tuned per defense; other settings would shift the trade-offs.
- Results describe this model, not what Mango or any other protocol would have experienced.

## Sources

- [CertiK alert, reported by ForkLog](https://forklog.com/news/haker-ukral-bolee-100-mln-s-defi-platformy-mango-markets)
- [ForkLog: Mango states oracles worked as intended](https://forklog.com/?p=187431)
- [Solidus Labs: The Mango Markets Exploit, an Order Book Analysis](https://www.soliduslabs.com/post/mango-hack)
