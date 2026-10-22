import json

import numpy as np
import pytest

from oraclelens import CAUSE_ID
from oraclelens.aggregators import run_aggregators
from oraclelens.config import config_hash, resolve
from oraclelens.detectors import run_detectors
from oraclelens.diagnosis import diagnose
from oraclelens.experiment import run_experiment
from oraclelens.metrics import (aggregation_metrics, breaking_point, brier_score,
                                detection_metrics, expected_calibration_error)
from oraclelens.simulator import simulate


def cfg(faults=None, **kw):
    return resolve({"rounds": 300, "faults": faults or [], **kw})


# ------------------------------------------------------------ reproducibility
def test_same_seed_same_results():
    c = cfg([{"type": "collusion", "count": 4, "start": 100}])
    a, *_ = run_experiment(c, 3, diagnose_incidents=True)
    b, *_ = run_experiment(c, 3, diagnose_incidents=True)
    assert a["provenance"]["data_hash"] == b["provenance"]["data_hash"]
    assert json.dumps(a["metrics"], sort_keys=True) == json.dumps(b["metrics"], sort_keys=True)


def test_different_seed_differs():
    c = cfg()
    assert run_experiment(c, 1)[0]["provenance"]["data_hash"] != \
        run_experiment(c, 2)[0]["provenance"]["data_hash"]


def test_config_hash_ignores_key_order():
    assert config_hash({"a": 1, "b": {"c": 2}}) == config_hash({"b": {"c": 2}, "a": 1})


def test_run_folder_contents(tmp_path):
    result, *_ = run_experiment(cfg([{"type": "outlier", "count": 2}]), 0, out_dir=tmp_path)
    files = {p.name for p in (tmp_path / "unnamed").iterdir().__next__().iterdir()}
    assert {"config.json", "provenance.json", "metrics.json", "events.parquet",
            "predictions.parquet", "incidents.parquet", "report.md"} <= files


# ------------------------------------------------------------------ simulator
def test_clean_run_has_no_injected_value_faults():
    sim = simulate(cfg(), 0)
    assert not np.isin(sim.labels, [1, 4, 5, 6, 7]).any()


def test_offline_nodes_report_nothing():
    sim = simulate(cfg([{"type": "offline", "count": 3, "start": 100, "end": 150}]), 0)
    nodes = sim.events[0]["nodes"]
    assert np.isnan(sim.obs[100:150, nodes]).all()
    assert (sim.labels[100:150, nodes] == CAUSE_ID["offline"]).all()


def test_stale_value_is_frozen():
    sim = simulate(cfg([{"type": "stale", "count": 1, "start": 100}]), 0)
    node = sim.events[0]["nodes"][0]
    assert np.ptp(sim.obs[100:, node]) == 0


def test_source_fault_hits_only_that_source():
    sim = simulate(cfg([{"type": "source_fault", "source": 2, "start": 100, "end": 120}]), 0)
    hit = (sim.labels[100:120] == CAUSE_ID["correlated_source"]).any(axis=0)
    assert set(np.flatnonzero(hit)) == set(np.flatnonzero(sim.source_of == 2))


def test_market_shock_moves_truth_without_labels():
    base = simulate(cfg(), 5).truth
    shocked = simulate(cfg([{"type": "market_shock", "start": 150, "size": -0.2, "duration": 2}]), 5)
    assert shocked.truth[200] == pytest.approx(base[200] * 0.8, rel=1e-9)
    assert not np.isin(shocked.labels, [1, 4, 5, 6, 7]).any()


# ---------------------------------------------------------------- aggregators
def test_median_robust_to_one_extreme_node():
    c = cfg([{"type": "collusion", "count": 1, "bias": 10.0, "start": 50}])
    sim = simulate(c, 0)
    m = aggregation_metrics(sim, run_aggregators(sim, c)["median"], 50, [0.01])
    assert m["failure_rate@0.01"] == 0.0


def test_quorum_median_goes_unavailable():
    c = cfg([{"type": "offline", "count": 10, "start": 100}])
    sim = simulate(c, 0)
    aggs = run_aggregators(sim, c)
    assert np.isnan(aggs["quorum_median"][120:]).all()
    assert not np.isnan(aggs["median"][120:]).any()


def test_majority_collusion_breaks_median():
    c = cfg([{"type": "collusion", "count": 11, "bias": 0.05, "start": 50}])
    sim = simulate(c, 0)
    m = aggregation_metrics(sim, run_aggregators(sim, c)["median"], 50, [0.01])
    assert m["failure_rate@0.01"] > 0.9


# ------------------------------------------------------------------ detectors
def test_detectors_quiet_on_clean_data():
    c = cfg()
    sim = simulate(c, 0)
    for name, f in run_detectors(sim, c).items():
        fpr = detection_metrics(sim, f, 50)["false_positive_rate"]
        assert fpr < 0.06, name


def test_mad_catches_large_outliers():
    c = cfg([{"type": "outlier", "count": 3, "prob": 0.3, "size": [0.05, 0.2]}])
    sim = simulate(c, 0)
    assert detection_metrics(sim, run_detectors(sim, c)["mad"], 50)["recall"] > 0.95


def test_cusum_catches_slow_drift():
    c = cfg([{"type": "drift", "count": 1, "start": 100, "rate": 0.0001}])
    sim = simulate(c, 0)
    m = detection_metrics(sim, run_detectors(sim, c)["cusum"], 50)
    assert m["faults_detected"] == 1.0 and m["precision"] > 0.9


# ------------------------------------------------------------------ diagnosis
@pytest.mark.parametrize("fault,expected", [
    ({"type": "offline", "count": 2, "start": 100, "end": 140}, "offline"),
    ({"type": "stale", "count": 1, "start": 100, "end": 200}, "stale"),
    ({"type": "collusion", "count": 4, "start": 100, "end": 160, "bias": 0.04}, "coordinated_manipulation"),
    ({"type": "drift", "count": 1, "start": 100, "rate": 0.0005}, "gradual_drift"),
])
def test_diagnosis_names_the_cause(fault, expected):
    c = cfg([fault])
    sim = simulate(c, 1)
    incidents = [i for i in diagnose(sim, run_detectors(sim, c), c) if i["true_cause"] == expected]
    assert incidents
    longest = max(incidents, key=lambda i: i["end"] - i["start"])
    assert longest["top_cause"] == expected


def test_probabilities_sum_to_one():
    c = cfg([{"type": "outlier", "count": 2}])
    sim = simulate(c, 0)
    for inc in diagnose(sim, run_detectors(sim, c), c):
        assert sum(inc["probs"]) == pytest.approx(1.0)


# -------------------------------------------------------------------- metrics
def test_ece_perfect_and_bad():
    assert expected_calibration_error([1.0, 1.0], [1, 1]) == 0.0
    assert expected_calibration_error([0.9, 0.9], [0, 0]) == pytest.approx(0.9)


def test_brier():
    assert brier_score(np.array([[1.0, 0.0]]), np.array([0])) == 0.0
    assert brier_score(np.array([[0.0, 1.0]]), np.array([0])) == 2.0


def test_breaking_point_definition():
    assert breaking_point([0, 0.2, 0.4], [0.0, 0.05, 0.06], 0.05) == 0.4   # strictly greater
    assert breaking_point([0, 0.2], [0.0, 0.01], 0.05) is None


# --------------------------------------------------------- randomized params
def test_random_params_are_reproducible_and_vary_by_seed():
    f = [{"type": "collusion", "count": 3, "bias": {"uniform": [0.01, 0.08]},
          "direction": {"choice": [-1, 1]}, "start": {"uniform": [60, 120]}}]
    a = simulate(cfg(f), 4).events[0]["params"]
    b = simulate(cfg(f), 4).events[0]["params"]
    c = simulate(cfg(f), 5).events[0]["params"]
    assert a == b and a != c
    assert 0.01 <= a["bias"] <= 0.08 and isinstance(a["start"], int)


def test_attack_draw_independent_of_attacker_count():
    base = {"type": "collusion", "bias": {"uniform": [0.01, 0.08]}}
    one = simulate(cfg([dict(base, count=1)]), 9).events[0]["params"]["bias"]
    five = simulate(cfg([dict(base, count=5)]), 9).events[0]["params"]["bias"]
    assert one == five
