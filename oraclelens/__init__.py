"""OracleLens: a reproducible laboratory for oracle failures, attacks and defenses."""

__version__ = "0.1.0"

CAUSES = [
    "none",
    "stale",
    "delayed",
    "offline",
    "isolated_outlier",
    "correlated_source",
    "gradual_drift",
    "coordinated_manipulation",
]
CAUSE_ID = {name: i for i, name in enumerate(CAUSES)}
INSUFFICIENT = "insufficient_evidence"

# Causes that corrupt a reported value (as opposed to removing or delaying it).
VALUE_FAULTS = [CAUSE_ID[c] for c in
                ("stale", "isolated_outlier", "correlated_source",
                 "gradual_drift", "coordinated_manipulation")]
