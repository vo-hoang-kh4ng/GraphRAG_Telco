"""Offline sanity + regression tests for the real DejaVu dataset
(src/kg/dejavu_data.py). No Neo4j needed -- same pattern as test_rule_engine.py.
"""

from src.graphrag.llm_client import MockLLM
from src.kg.dejavu_data import DEVICES, INCIDENTS
from src.rules.rule_engine import evaluate_rules, merge_candidates

DEVICE_IDS = {d["id"] for d in DEVICES}


def facts_for_incident(incident):
    devices = {d["id"]: {"type": d["type"]} for d in DEVICES}
    parents_of = {d["id"]: list(d["depends_on"]) for d in DEVICES}
    children_of = {}
    for dev_id, parents in parents_of.items():
        for parent_id in parents:
            children_of.setdefault(parent_id, []).append(dev_id)

    alarms_by_device = {}
    for a in incident["alarms"]:
        alarms_by_device.setdefault(a["device"], []).append({"type": a["type"], "severity": a["severity"]})

    return {
        "devices": devices,
        "parents_of": parents_of,
        "children_of": children_of,
        "alarms_by_device": alarms_by_device,
        "kpis_by_device": {},
    }


def test_topology_has_no_dangling_references():
    for d in DEVICES:
        for parent_id in d["depends_on"]:
            assert parent_id in DEVICE_IDS, f"{d['id']} depends_on unknown device {parent_id}"


def test_every_incident_root_cause_is_a_known_device():
    for inc in INCIDENTS:
        assert inc["ground_truth_root_cause"] in DEVICE_IDS
        for alarm in inc["alarms"]:
            assert alarm["device"] in DEVICE_IDS


def test_rule_engine_top1_matches_ground_truth_on_all_real_incidents():
    mismatches = []
    for inc in INCIDENTS:
        facts = facts_for_incident(inc)
        ranked = merge_candidates(evaluate_rules(facts))
        predicted = ranked[0].device_id if ranked else None
        if predicted != inc["ground_truth_root_cause"]:
            mismatches.append((inc["id"], inc["ground_truth_root_cause"], predicted))
    assert not mismatches, f"{len(mismatches)} mismatches: {mismatches[:5]}"


def test_mock_llm_matches_ground_truth_on_sample_of_real_incidents():
    devices_for_subgraph = [
        {"id": d["id"], "type": d["type"], "name": d["name"], "parent_ids": list(d["depends_on"]), "site_name": None}
        for d in DEVICES
    ]
    llm = MockLLM()
    # Full 78-incident sweep is covered by the rule-engine test above;
    # this spot-checks MockLLM's independent structural path on a subset.
    for inc in INCIDENTS[::10]:
        alarms = [{"device_id": a["device"], "type": a["type"], "severity": a["severity"]} for a in inc["alarms"]]
        subgraph = {
            "seed_devices": [a["device"] for a in inc["alarms"]],
            "devices": devices_for_subgraph,
            "alarms": alarms,
            "kpis": [],
            "services": [],
            "historical_incidents": [],
        }
        diagnosis = llm.diagnose(context_text="", subgraph=subgraph)
        assert diagnosis.root_cause_device == inc["ground_truth_root_cause"], (
            f"{inc['id']}: expected {inc['ground_truth_root_cause']}, got {diagnosis.root_cause_device}"
        )
