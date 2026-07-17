"""Tests for context_builder and MockLLM. No Neo4j needed: a subgraph dict is
built directly from the sample scenario/topology data, in the same shape
src.graphrag.retriever.retrieve_subgraph() would return.
"""

from src.graphrag.context_builder import build_context_text
from src.graphrag.llm_client import MockLLM
from src.kg.sample_data import DEVICES, SCENARIOS


def build_fake_subgraph(scenario):
    devices = [
        {"id": d["id"], "type": d["type"], "name": d["name"], "parent_ids": list(d["depends_on"]), "site_name": None}
        for d in DEVICES
    ]
    alarms = [{"device_id": a["device"], "type": a["type"], "severity": a["severity"]} for a in scenario["alarms"]]
    kpis = [
        {"device_id": k["device"], "name": k["kpi"], "value": k["value"], "status": k["status"]}
        for k in scenario["kpi_anomalies"]
    ]
    seed_devices = sorted({a["device_id"] for a in alarms} | {k["device_id"] for k in kpis})
    return {
        "incident_id": scenario["id"],
        "seed_devices": seed_devices,
        "devices": devices,
        "alarms": alarms,
        "kpis": kpis,
        "services": [],
        "historical_incidents": [],
    }


def test_context_text_mentions_all_active_alarms():
    scenario = next(s for s in SCENARIOS if s["id"] == "SCN-01")
    subgraph = build_fake_subgraph(scenario)
    text = build_context_text(subgraph)
    for alarm in scenario["alarms"]:
        assert alarm["device"] in text
        assert alarm["type"] in text


def test_context_text_handles_empty_seed():
    subgraph = {
        "seed_devices": [],
        "devices": [],
        "alarms": [],
        "kpis": [],
        "services": [],
        "historical_incidents": [],
    }
    text = build_context_text(subgraph)
    assert "Knowledge Graph" in text


def test_mock_llm_matches_ground_truth_on_all_scenarios():
    llm = MockLLM()
    for scenario in SCENARIOS:
        subgraph = build_fake_subgraph(scenario)
        diagnosis = llm.diagnose(context_text="", subgraph=subgraph)
        assert diagnosis.root_cause_device == scenario["ground_truth_root_cause"], (
            f"{scenario['id']}: expected {scenario['ground_truth_root_cause']}, got {diagnosis.root_cause_device}"
        )
        assert 0.0 < diagnosis.confidence <= 1.0
