# OracleLens run: mixed_faults (seed 42)

Config hash `386c8c17670872bb` · data hash `fc3d4bdd9eeb974d` · OracleLens 0.1.0

## Injected faults

- **market_shock** (none) on 0 node(s), rounds 300–303
- **outlier** (isolated_outlier) on 2 node(s), rounds 60–500
- **stale** (stale) on 1 node(s), rounds 120–220
- **replay** (stale) on 1 node(s), rounds 140–240
- **delay** (delayed) on 2 node(s), rounds 100–200
- **offline** (offline) on 2 node(s), rounds 250–280
- **source_fault** (correlated_source) on 4 node(s), rounds 350–380
- **drift** (gradual_drift) on 1 node(s), rounds 380–500
- **collusion** (coordinated_manipulation) on 3 node(s), rounds 420–470

## Aggregation

| Method | Mean error | p95 error | Failed rounds (>1.0%) | Availability |
| --- | --- | --- | --- | --- |
| median | 0.03% | 0.07% | 0.00% | 100.00% |
| trimmed_mean | 0.04% | 0.08% | 0.00% | 100.00% |
| weighted | 0.05% | 0.11% | 0.00% | 100.00% |
| reputation | 0.25% | 0.72% | 1.11% | 100.00% |
| quorum_median | 0.03% | 0.07% | 0.00% | 100.00% |

## Detection

| Detector | Precision | Recall | False-positive rate | Median latency (rounds) |
| --- | --- | --- | --- | --- |
| mad | 0.957 | 0.957 | 0.39% | 0.000 |
| hampel | 0.373 | 0.304 | 4.57% | 0.000 |
| rolling | 0.651 | 0.808 | 3.87% | 0.000 |
| cusum | 0.855 | 0.747 | 1.13% | 2.000 |
| vol_mad | 1.000 | 0.914 | 0.00% | 0.000 |

## Diagnosis

150 incidents · top-1 accuracy 94.7% · coverage 85.3% · ECE 0.138 · Brier 0.154

Largest non-trivial incidents:

- Node 9, rounds 381–499 (truth: gradual_drift). Likely gradual drift (90%): deviation grows steadily; 1 other node(s) deviate the same way (0 share its source); peak robust z = 57.4.
- Node 10, rounds 140–248 (truth: stale). Likely stale (93%): values match the consensus from earlier rounds; peak robust z = 205.7.
- Node 8, rounds 125–224 (truth: stale). Likely stale (91%): value repeated while the market moved; peak robust z = 83.7.
- Node 20, rounds 420–481 (truth: coordinated_manipulation). Insufficient evidence (best guess coordinated manipulation, 40%): 3 other node(s) deviate the same way (1 share its source); peak robust z = 79.3. Cannot establish: agreement among nodes does not show which side is correct.
- Node 0, rounds 420–478 (truth: coordinated_manipulation). Insufficient evidence (best guess coordinated manipulation, 38%): 3 other node(s) deviate the same way (1 share its source); peak robust z = 79.5. Cannot establish: agreement among nodes does not show which side is correct.
- Node 2, rounds 420–478 (truth: coordinated_manipulation). Likely coordinated manipulation (69%): 3 other node(s) deviate the same way (0 share its source); peak robust z = 79.3. Cannot establish: agreement among nodes does not show which side is correct.
- Node 4, rounds 143–185 (truth: delayed). Likely delayed (77%): late in 65% of reports; peak robust z = 1.7.
- Node 6, rounds 151–191 (truth: delayed). Likely delayed (78%): late in 66% of reports; peak robust z = 1.7.

_Thresholds here are OracleLens research benchmarks, not safety limits for any production oracle system._
