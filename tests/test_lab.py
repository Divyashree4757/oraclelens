from pathlib import Path

from fastapi.testclient import TestClient

from oraclelens.lab.page import render_page
from oraclelens.lab.server import create_app

ROOT = Path(__file__).resolve().parents[1]
client = TestClient(create_app(ROOT / "results", ROOT / "experiments"))


def test_index_page_is_live():
    r = client.get("/")
    assert r.status_code == 200
    assert '"live":true' in r.text and "OracleLens" in r.text


def test_presets_exclude_sweeps():
    names = [p["name"] for p in client.get("/api/presets").json()]
    assert "mixed_faults" in names and not any(n.startswith("bp_") for n in names)


def test_simulate_returns_aligned_arrays():
    body = {"seed": 3, "config": {"nodes": 9, "rounds": 120, "evaluation": {"warmup": 20},
                                  "faults": [{"type": "collusion", "count": 2, "start": 40}]}}
    d = client.post("/api/simulate", json=body).json()
    assert d["rounds"] == 120 and d["nodes"] == 9
    assert len(d["obs"]) == 120 and len(d["obs"][0]) == 9
    assert len(d["flags"]) == 120 and set(d["aggregates"]) >= {"median", "reputation"}
    assert d["events"][0]["type"] == "collusion"


def test_simulate_rejects_bad_input():
    assert client.post("/api/simulate", json={"config": {"faults": [{"type": "nope"}]}}).status_code == 400
    assert client.post("/api/simulate", json={"config": {"nodes": 500}}).status_code == 400


def test_static_page_escapes_script_close():
    page = render_page({"x": "</script><b>"}, live=False)
    assert "</script><b>" not in page and '"live":false' in page
