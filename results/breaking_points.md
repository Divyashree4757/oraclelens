# Breaking points

Smallest share of faulty nodes at which P(round error > tolerance) exceeds 5%, with a 95% bootstrap interval over seeds where it is not a single value. "never" means not reached within the sweep.

### Tolerance 0.5%

| Sweep | median | trimmed mean | weighted | reputation | quorum median |
| --- | --- | --- | --- | --- | --- |
| bp_collusion | 52% | 29% | 52% | 14% | 52% |
| bp_collusion_random | 52% | 24% | 52% | 14% | 52% |
| bp_independent | never | 29% | never | 10% [5%–10%] | never |
| bp_partition | never | never | never | never | never |
| bp_reputation_exploit | 52% | 29% | 52% | 14% | 52% |
| bp_reputation_exploit_random | 52% | 24% | 52% | 14% [14%–19%] | 52% |
| bp_slow_burn | 52% | 29% | 52% | 24% | 52% |
| bp_slow_burn_random | 52% | 24% | 52% | 24% [19%–29%] | 52% |
| bp_source | 62% | 43% | 62% | 24% | 62% |
| bp_source_random | 62% [62%–81%] | 43% | 62% [62%–81%] | 24% | 62% [62%–81%] |

### Tolerance 1.0%

| Sweep | median | trimmed mean | weighted | reputation | quorum median |
| --- | --- | --- | --- | --- | --- |
| bp_collusion | 52% | 33% | 52% | 24% [24%–29%] | 52% |
| bp_collusion_random | 52% | 29% | 52% | 24% [24%–29%] | 52% |
| bp_independent | never | 33% | never | 24% | never |
| bp_partition | never | never | never | never | never |
| bp_reputation_exploit | 52% | 33% | 52% | 29% | 52% |
| bp_reputation_exploit_random | 52% | 29% | 52% | 29% [24%–29%] | 52% |
| bp_slow_burn | 52% | 33% | 52% | 43% | 52% |
| bp_slow_burn_random | 52% | 29% [29%–33%] | 52% | 43% [38%–48%] | 52% |
| bp_source | 62% | 43% | 62% | 43% | 62% |
| bp_source_random | 62% [62%–81%] | 43% | 62% [62%–81%] | 43% [43%–81%] | 62% [62%–81%] |

### Tolerance 2.0%

| Sweep | median | trimmed mean | weighted | reputation | quorum median |
| --- | --- | --- | --- | --- | --- |
| bp_collusion | 52% | 48% | 52% | 48% | 52% |
| bp_collusion_random | 52% | 38% | 52% | 43% [43%–52%] | 52% |
| bp_independent | never | 43% | never | 57% | never |
| bp_partition | never | never | never | never | never |
| bp_reputation_exploit | 52% | 48% | 52% | 48% | 52% |
| bp_reputation_exploit_random | 52% | 38% [38%–43%] | 52% | 48% [43%–52%] | 52% |
| bp_slow_burn | 52% | 48% | 52% | 52% | 52% |
| bp_slow_burn_random | 52% | 38% [38%–43%] | 52% | 52% | 52% |
| bp_source | 62% | 62% | 62% | 62% | 62% |
| bp_source_random | 62% [62%–81%] | 62% [62%–81%] | 62% [62%–81%] | 62% [62%–81%] | 62% [62%–81%] |
