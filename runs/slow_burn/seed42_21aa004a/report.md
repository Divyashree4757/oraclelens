# OracleLens run: slow_burn (seed 42)

Config hash `21aa004ab93d74ce` · data hash `d1326619bf2bfe3f` · OracleLens 0.1.0

## Injected faults

- **slow_burn** (gradual_drift) on 5 node(s), rounds 150–500

## Aggregation

| Method | Mean error | p95 error | Failed rounds (>1.0%) | Availability |
| --- | --- | --- | --- | --- |
| median | 0.03% | 0.09% | 0.00% | 100.00% |
| trimmed_mean | 0.28% | 0.45% | 0.00% | 100.00% |
| weighted | 0.03% | 0.09% | 0.00% | 100.00% |
| reputation | 0.21% | 0.55% | 0.00% | 100.00% |
| quorum_median | 0.03% | 0.09% | 0.00% | 100.00% |

## Detection

| Detector | Precision | Recall | False-positive rate | Median latency (rounds) |
| --- | --- | --- | --- | --- |
| mad | 0.965 | 0.975 | 0.79% | 9.000 |
| hampel | 0.153 | 0.026 | 3.31% | 2.000 |
| rolling | 0.871 | 0.901 | 3.03% | 16.000 |
| cusum | 1.000 | 0.974 | 0.00% | 9.000 |
| vol_mad | 1.000 | 0.958 | 0.00% | 10.000 |

## Diagnosis

64 incidents · top-1 accuracy 78.1% · coverage 95.3% · ECE 0.181 · Brier 0.307

Largest non-trivial incidents:

- Node 3, rounds 159–499 (truth: gradual_drift). Likely gradual drift (95%): deviation grows steadily; 4 other node(s) deviate the same way (0 share its source); peak robust z = 134.3. Cannot establish: agreement among nodes does not show which side is correct.
- Node 4, rounds 159–499 (truth: gradual_drift). Likely gradual drift (95%): deviation grows steadily; 4 other node(s) deviate the same way (0 share its source); peak robust z = 133.9. Cannot establish: agreement among nodes does not show which side is correct.
- Node 7, rounds 159–499 (truth: gradual_drift). Likely gradual drift (95%): late in 0% of reports; deviation grows steadily; 4 other node(s) deviate the same way (1 share its source); peak robust z = 134.2. Cannot establish: agreement among nodes does not show which side is correct.
- Node 9, rounds 159–499 (truth: gradual_drift). Likely gradual drift (95%): deviation grows steadily; 4 other node(s) deviate the same way (1 share its source); peak robust z = 134.0. Cannot establish: agreement among nodes does not show which side is correct.
- Node 10, rounds 159–499 (truth: gradual_drift). Likely gradual drift (95%): deviation grows steadily; 4 other node(s) deviate the same way (0 share its source); peak robust z = 134.0. Cannot establish: agreement among nodes does not show which side is correct.
- Node 13, rounds 109–112 (truth: none). Likely isolated outlier (76%): peak robust z = 6.4.
- Node 14, rounds 50–53 (truth: none). Likely isolated outlier (54%): peak robust z = 4.4.
- Node 14, rounds 453–456 (truth: delayed). Insufficient evidence (best guess isolated outlier, 29%): late in 25% of reports; peak robust z = 3.8.

## Slow-burn attack

| Aggregator | Rounds to success | Rounds to detection (MAD) | Damage before detection (MAD) |
| --- | --- | --- | --- |
| median | – | 9 | 0.003 |
| trimmed_mean | – | 9 | 0.005 |
| weighted | – | 9 | 0.007 |
| reputation | – | 9 | 0.006 |
| quorum_median | – | 9 | 0.003 |

_Thresholds here are OracleLens research benchmarks, not safety limits for any production oracle system._
